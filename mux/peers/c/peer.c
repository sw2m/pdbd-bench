// see mux/README.md "Comparators"
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <malloc.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <nghttp2/nghttp2.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#define CONNECTION (1 << 30) // see mux/README.md "Fairness"

struct params {
  long window, chunk, bulk, flows, message, pings, warm, load, churn, idle;
  double timeout;
};

struct end {
  long pending, rx;
  int eof;
};

struct flow {
  int32_t id;
  struct end near, far;
  int stall, echo, close, accepted, closed;
  double opened, arrived, done;
  long want;
};

enum { NEAR, FAR };

struct side {
  int which;
  nghttp2_session *s;
  int fd;
  const uint8_t *pend;
  size_t plen;
};

static struct params P;
static int CORE;
static struct side SIDES[2];
static struct flow **FLOWS;
static size_t NFLOWS;
static uint8_t *DATA;

static void fail(const char *format, ...) {
  va_list args;
  va_start(args, format);
  fprintf(stderr, "peer: nghttp2: ");
  vfprintf(stderr, format, args);
  fprintf(stderr, "\n");
  va_end(args);
  exit(2);
}

static double now(void) {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return t.tv_sec + t.tv_nsec / 1e9;
}

static double cpu(void) {
  struct rusage u;
  getrusage(RUSAGE_SELF, &u);
  return (u.ru_utime.tv_sec + u.ru_stime.tv_sec) * 1e3 + (u.ru_utime.tv_usec + u.ru_stime.tv_usec) / 1e3;
}

static double status(const char *field) {
  FILE *f = fopen("/proc/self/status", "r");
  char line[256];
  size_t n = strlen(field);
  double out = -1;
  while (f && fgets(line, sizeof line, f)) {
    if (!strncmp(line, field, n) && line[n] == ':') {
      out = atof(line + n + 1) * 1024;
      break;
    }
  }
  if (f) fclose(f);
  if (out < 0) fail("/proc/self/status has no %s", field);
  return out;
}

static struct flow *find(int32_t id) {
  size_t i = (size_t)(id - 1) / 2;
  return id > 0 && (id & 1) && i < NFLOWS ? FLOWS[i] : NULL;
}

static struct flow *track(int32_t id) {
  size_t i = (size_t)(id - 1) / 2;
  if (i >= NFLOWS) {
    size_t grown = NFLOWS ? NFLOWS * 2 : 1024;
    while (grown <= i) grown *= 2;
    FLOWS = realloc(FLOWS, grown * sizeof *FLOWS);
    memset(FLOWS + NFLOWS, 0, (grown - NFLOWS) * sizeof *FLOWS);
    NFLOWS = grown;
  }
  if (!FLOWS[i]) FLOWS[i] = calloc(1, sizeof(struct flow));
  FLOWS[i]->id = id;
  return FLOWS[i];
}

static nghttp2_ssize source(nghttp2_session *s, int32_t id, uint8_t *buf, size_t length, uint32_t *flags,
                            nghttp2_data_source *src, void *user) {
  (void)s, (void)src;
  struct flow *f = find(id);
  int side = ((struct side *)user)->which;
  struct end *e = side == NEAR ? &f->near : &f->far;
  long *pending = &e->pending;
  int eof = e->eof;
  if (*pending == 0) {
    if (eof) {
      *flags |= NGHTTP2_DATA_FLAG_EOF;
      return 0;
    }
    return NGHTTP2_ERR_DEFERRED;
  }
  size_t n = length;
  if ((long)n > *pending) n = (size_t)*pending;
  if ((long)n > P.chunk) n = (size_t)P.chunk;
  memcpy(buf, DATA, n);
  *pending -= (long)n;
  if (*pending == 0 && eof) *flags |= NGHTTP2_DATA_FLAG_EOF;
  return (nghttp2_ssize)n;
}

static void more(int side, struct flow *f, long n) {
  (side == NEAR ? &f->near : &f->far)->pending += n;
  nghttp2_session_resume_data(SIDES[side].s, f->id);
}

static int on_chunk(nghttp2_session *s, uint8_t flags, int32_t id, const uint8_t *data, size_t len, void *user) {
  (void)flags, (void)data;
  struct flow *f = find(id);
  int side = ((struct side *)user)->which;
  if (!f) return 0;
  if (side == FAR) {
    f->far.rx += (long)len;
    if (!f->stall) nghttp2_session_consume(s, id, len);
    if (f->want && f->far.rx >= f->want && !f->done) f->done = now();
    if (f->echo) {
      if (f->close) f->far.eof = 1;
      more(FAR, f, (long)len);
    }
  } else {
    f->near.rx += (long)len;
    nghttp2_session_consume(s, id, len);
  }
  return 0;
}

static int on_frame(nghttp2_session *s, const nghttp2_frame *frame, void *user) {
  if (((struct side *)user)->which != FAR || frame->hd.type != NGHTTP2_HEADERS ||
      frame->headers.cat != NGHTTP2_HCAT_REQUEST)
    return 0;
  struct flow *f = find(frame->hd.stream_id);
  if (!f) return 0;
  f->accepted = 1;
  f->arrived = now();
  nghttp2_nv status[] = {{(uint8_t *)":status", (uint8_t *)"200", 7, 3, NGHTTP2_NV_FLAG_NONE}};
  nghttp2_data_provider2 provider = {.read_callback = source};
  return nghttp2_submit_response2(s, frame->hd.stream_id, status, 1, &provider);
}

static int on_close(nghttp2_session *s, int32_t id, uint32_t code, void *user) {
  (void)s, (void)code;
  struct flow *f = find(id);
  if (f && ((struct side *)user)->which == NEAR) f->closed = 1;
  return 0;
}

static nghttp2_session *session(int which) {
  nghttp2_session_callbacks *cb;
  nghttp2_session_callbacks_new(&cb);
  nghttp2_session_callbacks_set_on_data_chunk_recv_callback(cb, on_chunk);
  nghttp2_session_callbacks_set_on_frame_recv_callback(cb, on_frame);
  nghttp2_session_callbacks_set_on_stream_close_callback(cb, on_close);
  nghttp2_option *opt;
  nghttp2_option_new(&opt);
  nghttp2_option_set_no_auto_window_update(opt, 1);  // see mux/README.md "Fairness"
  nghttp2_option_set_no_closed_streams(opt, 1);
  nghttp2_session *s;
  SIDES[which].which = which;
  int rv = which == NEAR ? nghttp2_session_client_new2(&s, cb, &SIDES[which], opt)
                         : nghttp2_session_server_new2(&s, cb, &SIDES[which], opt);
  if (rv) fail("session: %s", nghttp2_strerror(rv));
  nghttp2_option_del(opt);
  nghttp2_session_callbacks_del(cb);
  long limit = P.flows;
  if (P.load + 1 > limit) limit = P.load + 1;
  if (P.idle > limit) limit = P.idle;
  if (P.churn > limit) limit = P.churn;
  nghttp2_settings_entry settings[] = {
      {NGHTTP2_SETTINGS_INITIAL_WINDOW_SIZE, (uint32_t)P.window},
      {NGHTTP2_SETTINGS_MAX_CONCURRENT_STREAMS, (uint32_t)limit + 1},  // see mux/README.md "Fairness"
  };
  nghttp2_submit_settings(s, NGHTTP2_FLAG_NONE, settings, 2);
  nghttp2_session_set_local_window_size(s, NGHTTP2_FLAG_NONE, 0, CONNECTION);
  return s;
}

static void loopback(int fds[2]) {
  int l = socket(AF_INET, SOCK_STREAM, 0);
  struct sockaddr_in a = {.sin_family = AF_INET, .sin_addr.s_addr = htonl(INADDR_LOOPBACK)};
  socklen_t alen = sizeof a;
  if (bind(l, (struct sockaddr *)&a, sizeof a) || listen(l, 1) || getsockname(l, (struct sockaddr *)&a, &alen))
    fail("listen: %s", strerror(errno));
  fds[NEAR] = socket(AF_INET, SOCK_STREAM, 0);
  if (connect(fds[NEAR], (struct sockaddr *)&a, sizeof a)) fail("connect: %s", strerror(errno));
  fds[FAR] = accept(l, NULL, NULL);
  close(l);
  for (int i = 0; i < 2; i++) {
    int one = 1;
    setsockopt(fds[i], IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
    fcntl(fds[i], F_SETFL, fcntl(fds[i], F_GETFL) | O_NONBLOCK);
  }
}

static int pump(void) {
  int moved = 0;
  if (CORE) {
    for (int i = 0; i < 2; i++) {
      const uint8_t *d;
      nghttp2_ssize n;
      while ((n = nghttp2_session_mem_send2(SIDES[i].s, &d)) > 0) {
        nghttp2_ssize r = nghttp2_session_mem_recv2(SIDES[1 - i].s, d, (size_t)n);
        if (r < 0) fail("mem_recv2: %s", nghttp2_strerror((int)r));
        moved = 1;
      }
      if (n < 0) fail("mem_send2: %s", nghttp2_strerror((int)n));
    }
    return moved;
  }
  static uint8_t buf[1 << 16];
  for (int i = 0; i < 2; i++) {
    struct side *sd = &SIDES[i];
    for (;;) {
      if (!sd->plen) {
        nghttp2_ssize n = nghttp2_session_mem_send2(sd->s, &sd->pend);
        if (n < 0) fail("mem_send2: %s", nghttp2_strerror((int)n));
        sd->plen = (size_t)n;
        if (!n) break;
      }
      ssize_t w = write(sd->fd, sd->pend, sd->plen);
      if (w < 0) {
        if (errno == EAGAIN) break;
        fail("write: %s", strerror(errno));
      }
      sd->pend += w, sd->plen -= (size_t)w, moved = 1;
    }
    ssize_t r = read(sd->fd, buf, sizeof buf);
    if (r > 0) {
      nghttp2_ssize n = nghttp2_session_mem_recv2(sd->s, buf, (size_t)r);
      if (n < 0) fail("mem_recv2: %s", nghttp2_strerror((int)n));
      moved = 1;
    } else if (r < 0 && errno != EAGAIN) {
      fail("read: %s", strerror(errno));
    }
  }
  return moved;
}

static void setup(void) {
  for (size_t i = 0; i < NFLOWS; i++) free(FLOWS[i]);
  free(FLOWS);
  FLOWS = NULL, NFLOWS = 0;
  memset(SIDES, 0, sizeof SIDES);
  int fds[2] = {-1, -1};
  if (!CORE) loopback(fds);
  for (int i = 0; i < 2; i++) {
    SIDES[i].fd = fds[i];
    SIDES[i].s = session(i);
  }
}

static void teardown(void) {
  for (int i = 0; i < 2; i++) {
    nghttp2_session_del(SIDES[i].s);
    if (SIDES[i].fd >= 0) close(SIDES[i].fd);
  }
}

static struct flow *open1(void) {
  nghttp2_nv nv[] = {
      {(uint8_t *)":method", (uint8_t *)"POST", 7, 4, NGHTTP2_NV_FLAG_NONE},
      {(uint8_t *)":scheme", (uint8_t *)"http", 7, 4, NGHTTP2_NV_FLAG_NONE},
      {(uint8_t *)":path", (uint8_t *)"/", 5, 1, NGHTTP2_NV_FLAG_NONE},
      {(uint8_t *)":authority", (uint8_t *)"peer", 10, 4, NGHTTP2_NV_FLAG_NONE},
  };
  nghttp2_data_provider2 provider = {.read_callback = source};
  int32_t id = nghttp2_submit_request2(SIDES[NEAR].s, NULL, nv, 4, &provider, NULL);
  if (id < 0) fail("submit_request2: %s", nghttp2_strerror(id));
  struct flow *f = track(id);
  f->opened = now();
  return f;
}

static int until(int (*done)(void *), void *arg) {
  double end = now() + P.timeout;
  while (!done(arg)) {
    pump();
    if (now() > end) return 0;
  }
  return 1;
}

struct many {
  struct flow **f;
  long n, want;
};

static int primed(void *arg) {
  struct many *m = arg;
  for (long i = 0; i < m->n; i++)
    if (m->f[i]->far.rx < 1) return 0;
  return 1;
}

static int echoed(void *arg) {
  struct many *m = arg;
  for (long i = 0; i < m->n; i++)
    if (m->f[i]->near.rx < 1) return 0;
  return 1;
}

// see mux/README.md "Scenarios"
static struct flow **opened(long n) {
  struct flow **f = calloc((size_t)n, sizeof *f);
  for (long i = 0; i < n; i++) {
    f[i] = open1();
    f[i]->echo = 1;
    f[i]->near.pending = 1;
  }
  struct many m = {f, n, 0};
  if (!until(primed, &m) || !until(echoed, &m)) fail("opening %ld flows missed the deadline", n);
  for (long i = 0; i < n; i++) f[i]->echo = 0;
  return f;
}

static int received(void *arg) {
  struct many *m = arg;
  for (long i = 0; i < m->n; i++)
    if (m->f[i]->far.rx < m->want) return 0;
  return 1;
}

static double mib(long bytes, double secs) { return bytes / (double)(1 << 20) / secs; }

struct value {
  const char *unit;
  double v;
};

static struct value OUT[8];
static int NOUT;
static const char *VERDICT;

static void put(const char *unit, double v) { OUT[NOUT++] = (struct value){unit, v}; }

static void bulk(void) {
  struct flow **f = opened(1);
  double start = now();
  f[0]->want = 1 + P.bulk;
  more(NEAR, f[0], P.bulk);
  struct many m = {f, 1, 1 + P.bulk};
  if (!until(received, &m)) fail("bulk missed the deadline");
  put("MiB/s", mib(P.bulk, f[0]->done - start));
}

static int cmp(const void *a, const void *b) {
  double x = *(const double *)a, y = *(const double *)b;
  return (x > y) - (x < y);
}

static void flows(void) {
  long n = P.flows, share = P.bulk / n;
  if (n < 1) fail("flows is %ld: at least one", n);
  struct flow **f = opened(n);
  double start = now();
  for (long i = 0; i < n; i++) {
    f[i]->want = 1 + share;
    more(NEAR, f[i], share);
  }
  struct many m = {f, n, 1 + share};
  if (!until(received, &m)) fail("flows missed the deadline");
  double *rates = calloc((size_t)n, sizeof *rates), sum = 0, squares = 0, last = start;
  for (long i = 0; i < n; i++) {
    rates[i] = mib(share, f[i]->done - start);
    sum += rates[i], squares += rates[i] * rates[i];
    if (f[i]->done > last) last = f[i]->done;
  }
  qsort(rates, (size_t)n, sizeof *rates, cmp);
  put("MiB/s", mib(share * n, last - start));
  put("jain", sum * sum / (n * squares));
  put("slowest", rates[0] / rates[n / 2]);
}

static void isolation(int stalled) {
  double begin = status("VmRSS");
  long n = P.flows, share = P.bulk / n;
  struct flow **f = opened(n);
  f[0]->stall = 1;
  if (stalled) more(NEAR, f[0], share);
  double start = now();
  for (long i = 1; i < n; i++) {
    f[i]->want = 1 + share;
    more(NEAR, f[i], share);
  }
  struct many m = {f + 1, n - 1, 1 + share};
  if (!until(received, &m)) {
    VERDICT = "err";
    return;
  }
  double last = start;
  for (long i = 1; i < n; i++)
    if (f[i]->done > last) last = f[i]->done;
  put("MiB/s", mib(share * (n - 1), last - start));
  put("peak B", status("VmHWM") - begin);
}

struct back {
  struct flow *f;
  long want;
};

static int returned(void *arg) {
  struct back *b = arg;
  return b->f->near.rx >= b->want;
}

static void percentiles(double *micros, long n, const char *prefix) {
  qsort(micros, (size_t)n, sizeof *micros, cmp);
  static char names[3][32];
  snprintf(names[0], 32, "%sp50 µs", prefix);
  snprintf(names[1], 32, "%sp99 µs", prefix);
  put(names[0], micros[(long)(0.50 * (n - 1))]);
  put(names[1], micros[(long)(0.99 * (n - 1))]);
  if (!*prefix) put("p999 µs", micros[(long)(0.999 * (n - 1))]);
}

static void pingpong(long load) {
  struct flow **f = opened(1 + load);
  for (long i = 1; i <= load; i++) more(NEAR, f[i], 1L << 62);
  f[0]->echo = 1;
  double *trips = calloc((size_t)P.pings, sizeof *trips);
  for (long i = 0; i < P.warm + P.pings; i++) {
    double start = now();
    struct back b = {f[0], f[0]->near.rx + P.message};
    more(NEAR, f[0], P.message);
    if (!until(returned, &b)) fail("a round trip missed the deadline");
    if (i >= P.warm) trips[i - P.warm] = (now() - start) * 1e6;
  }
  percentiles(trips, P.pings, "");
}

static int arrived(void *arg) { return ((struct flow *)arg)->accepted; }
static int closed(void *arg) { return ((struct flow *)arg)->closed; }

static void churn(void) {
  double *waits = calloc((size_t)P.churn, sizeof *waits);
  double start = now();
  for (long i = 0; i < P.churn; i++) {
    struct flow *f = open1();
    f->echo = 1;
    f->close = 1;
    more(NEAR, f, 1);
    if (!until(arrived, f)) fail("an open missed the deadline");
    waits[i] = (f->arrived - f->opened) * 1e6;
    struct back b = {f, 1};
    if (!until(returned, &b)) fail("an echo missed the deadline");
    f->near.eof = 1;
    nghttp2_session_resume_data(SIDES[NEAR].s, f->id);
    if (!until(closed, f)) fail("a close missed the deadline");
  }
  put("cycles/s", P.churn / (now() - start));
  percentiles(waits, P.churn, "open ");
}

static double rss(void) {
  malloc_trim(0);
  return status("VmRSS");
}

static void idle(void) {
  double before = rss();
  opened(P.idle);
  put("B/flow", (rss() - before) / P.idle);
}

static void once(const char *scenario) {
  NOUT = 0;
  VERDICT = "ok";
  setup();
  if (!strcmp(scenario, "bulk")) bulk();
  else if (!strcmp(scenario, "flows")) flows();
  else if (!strcmp(scenario, "isolation")) isolation(1);
  else if (!strcmp(scenario, "calm")) isolation(0);
  else if (!strcmp(scenario, "pingpong")) pingpong(0);
  else if (!strcmp(scenario, "loaded")) pingpong(P.load);
  else if (!strcmp(scenario, "churn")) churn();
  else if (!strcmp(scenario, "idle")) idle();
  else fail("unsupported scenario %s", scenario);
  teardown();
}

static long field(const char *json, const char *key, long otherwise) {
  char needle[64];
  snprintf(needle, sizeof needle, "\"%s\":", key);
  const char *at = strstr(json, needle);
  return at ? atol(at + strlen(needle)) : otherwise;
}

int main(int argc, char **argv) {
  if (argc == 3 && !strcmp(argv[1], "version")) {
    if (strcmp(argv[2], "nghttp2-core") && strcmp(argv[2], "nghttp2-loopback")) fail("unknown impl %s", argv[2]);
    puts(nghttp2_version(0)->version_str);
    return 0;
  }
  if (argc != 4) fail("usage: peer <nghttp2-core|nghttp2-loopback> <scenario> <params json> | peer version <impl>");
  if (!strcmp(argv[1], "nghttp2-core")) CORE = 1;
  else if (strcmp(argv[1], "nghttp2-loopback")) fail("unknown impl %s", argv[1]);
  const char *j = argv[3], *scenario = argv[2];
  P = (struct params){field(j, "window", 262144), field(j, "chunk", 65536), field(j, "bulk", 268435456),
                      field(j, "flows", 16), field(j, "message", 64), field(j, "pings", 10000),
                      field(j, "warm", 100), field(j, "load", 4), field(j, "churn", 1000),
                      field(j, "idle", 1000), (double)field(j, "timeout", 60)};
  DATA = malloc((size_t)P.chunk);
  memset(DATA, 0x5a, (size_t)P.chunk);
  // see mux/README.md "Statistics"
  if (!strcmp(scenario, "isolation")) once("calm");
  once(scenario);
  double calm = 0;
  if (!strcmp(scenario, "isolation")) {
    once("calm");
    if (strcmp(VERDICT, "ok")) fail("the calm baseline missed the deadline");
    calm = OUT[0].v;
    FILE *c = fopen("/proc/self/clear_refs", "w");
    if (!c || fputs("5", c) < 0) fail("resetting the peak RSS: %s", strerror(errno));
    fclose(c);
  }
  double before = cpu();
  once(scenario);
  put("cpu ms", cpu() - before);
  if (calm && !strcmp(VERDICT, "ok")) {
    double stalled = OUT[0].v;
    put("calm MiB/s", calm);
    put("ratio", stalled / calm);
  }
  printf("{\"values\":{");
  for (int i = 0; i < NOUT; i++) printf("%s\"%s\":%.17g", i ? "," : "", OUT[i].unit, OUT[i].v);
  printf("},\"verdict\":\"%s\"}\n", VERDICT);
  return 0;
}
