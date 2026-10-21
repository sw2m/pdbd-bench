#define _GNU_SOURCE
#include "peer.h"

#include <dwnx/dwnx.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

struct ring {
  struct flow **at;
  size_t head, count, cap;
};

static dwnx_conn *CONNS[2];
static int WHICH[2] = {NEAR, FAR};
static int READY[2];
static struct ring RINGS[2];
static uint8_t RECORD[2][DWNX_DEFAULT_MAX_RECORD_SIZE];

static const char *version(void) { return DWNX_VERSION; }

static size_t slot(int64_t id) { return id >= 0 && (id & 3) == 0 ? (size_t)(id >> 2) : SIZE_MAX; }

static dwnx_tstamp stamp(void) {
  struct timespec t;
  clock_gettime(CLOCK_MONOTONIC, &t);
  return (dwnx_tstamp)t.tv_sec * DWNX_SECONDS + (dwnx_tstamp)t.tv_nsec;
}

static void push(int side, struct flow *f) {
  struct end *e = end(side, f);
  struct ring *r = &RINGS[side];
  if (e->queued) return;
  if (r->count == r->cap) {
    size_t cap = r->cap ? r->cap * 2 : 1024;
    struct flow **at = malloc(cap * sizeof *at);
    for (size_t i = 0; i < r->count; i++) at[i] = r->at[(r->head + i) % r->cap];
    free(r->at);
    *r = (struct ring){at, 0, r->count, cap};
  }
  r->at[(r->head + r->count++) % r->cap] = f;
  e->queued = 1;
}

static struct flow *front(int side) {
  struct ring *r = &RINGS[side];
  return r->count ? r->at[r->head] : NULL;
}

static struct flow *pop(int side) {
  struct ring *r = &RINGS[side];
  struct flow *f = r->at[r->head];
  r->head = (r->head + 1) % r->cap;
  r->count--;
  end(side, f)->queued = 0;
  return f;
}

static int due(struct end *e) { return e->pending > 0 || (e->eof && !e->ended); }

static void noise(uint8_t *dest, size_t len) {
  for (size_t i = 0; i < len; i++) dest[i] = (uint8_t)random();
}

static int params(dwnx_conn *c, const dwnx_transport_params *p, void *user) {
  (void)c, (void)p;
  READY[*(int *)user] = 1;
  return 0;
}

static int data(dwnx_conn *c, uint32_t flags, int64_t id, uint64_t offset, const uint8_t *d, size_t len, void *user,
                void *stream) {
  (void)flags, (void)offset, (void)d, (void)stream;
  struct flow *f = find(id);
  if (f && len && got(*(int *)user, f, len)) {
    dwnx_conn_extend_max_stream_offset(c, id, len);
    dwnx_conn_extend_max_offset(c, len);
  }
  return 0;
}

static int arrived(dwnx_conn *c, int64_t id, void *user) {
  (void)c;
  struct flow *f = find(id);
  if (f && *(int *)user == FAR) arrive(f);
  return 0;
}

static int closed(dwnx_conn *c, uint32_t flags, int64_t id, uint64_t rx, uint64_t tx, void *user, void *stream) {
  (void)flags, (void)rx, (void)tx, (void)stream;
  struct flow *f = find(id);
  if (*(int *)user == FAR) dwnx_conn_extend_max_streams_bidi(c, 1);
  else if (f) shut(f);
  return 0;
}

static int credit(dwnx_conn *c, int64_t id, uint64_t max, void *user, void *stream) {
  (void)c, (void)max, (void)stream;
  int side = *(int *)user;
  struct flow *f = find(id);
  if (f && due(end(side, f))) push(side, f);
  return 0;
}

static void start(int side) {
  dwnx_callbacks cb = {
      .rand = noise,
      .recv_transport_params = params,
      .recv_stream_data = data,
      .stream_open = arrived,
      .stream_close = closed,
      .extend_max_stream_data = credit,
  };
  dwnx_settings settings;
  dwnx_settings_default(&settings);
  settings.initial_ts = stamp();
  dwnx_transport_params tp;
  dwnx_transport_params_default(&tp);
  tp.initial_max_stream_data_bidi_local = (uint64_t)P.window;
  tp.initial_max_stream_data_bidi_remote = (uint64_t)P.window;
  tp.initial_max_data = CONNECTION;
  tp.initial_max_streams_bidi = (uint64_t)limit(); // see mux/README.md "Fairness"
  READY[side] = 0;
  RINGS[side] = (struct ring){0};
  int rv = side == NEAR ? dwnx_conn_client_new(&CONNS[side], &cb, &settings, &tp, NULL, &WHICH[side])
                        : dwnx_conn_server_new(&CONNS[side], &cb, &settings, &tp, NULL, &WHICH[side]);
  if (rv) fail("conn: %s", dwnx_strerror(rv));
}

static int up(void) { return READY[NEAR] && READY[FAR]; }

static void stop(int side) {
  dwnx_conn_del(CONNS[side]);
  free(RINGS[side].at);
}

static int64_t begin(void) {
  int64_t id;
  int rv = dwnx_conn_open_bidi_stream(CONNS[NEAR], &id, NULL);
  if (rv) fail("open_bidi_stream: %s", dwnx_strerror(rv));
  return id;
}

static void resume(int side, struct flow *f) {
  if (due(end(side, f))) push(side, f);
}

static ssize_t emit(int side, const uint8_t **out) {
  dwnx_conn *c = CONNS[side];
  for (;;) {
    struct flow *f = dwnx_conn_get_max_data_left(c) ? front(side) : NULL;
    int64_t id = -1;
    dwnx_vec v = {DATA, 0};
    uint32_t flags = DWNX_WRITE_STREAM_FLAG_NONE;
    int fin = 0;
    if (f) {
      id = f->id;
      v.len = take(side, f, SIZE_MAX, &fin);
      if (fin) flags |= DWNX_WRITE_STREAM_FLAG_FIN;
    }
    dwnx_ssize n = -1;
    dwnx_ssize w = dwnx_conn_writev_stream(c, RECORD[side], sizeof RECORD[side], &n, flags, id, &v, v.len ? 1 : 0, stamp());
    if (f && n >= 0) {
      struct end *e = end(side, f);
      e->pending -= (long)n;
      if (fin && (size_t)n == v.len) e->ended = 1;
      pop(side);
      if (due(e)) push(side, f);
    }
    if (w == DWNX_ERR_WRITE_MORE) continue;
    if (w == DWNX_ERR_STREAM_DATA_BLOCKED || w == DWNX_ERR_STREAM_SHUT_WR) {
      pop(side);
      continue;
    }
    if (w < 0) fail("writev_stream (stream %lld, %zu bytes): %s", (long long)id, v.len, dwnx_strerror((int)w));
    *out = RECORD[side];
    return w;
  }
}

static void feed(int side, const uint8_t *data, size_t len) {
  int rv = dwnx_conn_read(CONNS[side], data, len, stamp());
  if (rv) fail("read: %s", dwnx_strerror(rv));
}

const struct lib DWNX = {"dwnx", version, slot, start, up, stop, begin, resume, emit, feed};
