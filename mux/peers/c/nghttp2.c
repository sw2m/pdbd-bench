#include "peer.h"

#include <nghttp2/nghttp2.h>
#include <string.h>

static nghttp2_session *SESSIONS[2];
static int WHICH[2] = {NEAR, FAR};

static const char *version(void) { return nghttp2_version(0)->version_str; }

static size_t slot(int64_t id) { return id > 0 && (id & 1) ? (size_t)(id - 1) / 2 : SIZE_MAX; }

static nghttp2_ssize source(nghttp2_session *s, int32_t id, uint8_t *buf, size_t length, uint32_t *flags,
                            nghttp2_data_source *src, void *user) {
  (void)s, (void)src;
  int side = *(int *)user;
  struct flow *f = find(id);
  struct end *e = end(side, f);
  if (e->pending == 0) {
    if (e->eof) {
      *flags |= NGHTTP2_DATA_FLAG_EOF;
      return 0;
    }
    return NGHTTP2_ERR_DEFERRED;
  }
  int fin;
  size_t n = take(side, f, length, &fin);
  memcpy(buf, DATA, n);
  e->pending -= (long)n;
  if (fin) *flags |= NGHTTP2_DATA_FLAG_EOF;
  return (nghttp2_ssize)n;
}

static int chunk(nghttp2_session *s, uint8_t flags, int32_t id, const uint8_t *data, size_t len, void *user) {
  (void)flags, (void)data;
  struct flow *f = find(id);
  if (f && got(*(int *)user, f, len)) nghttp2_session_consume(s, id, len);
  return 0;
}

static int request(nghttp2_session *s, const nghttp2_frame *frame, void *user) {
  if (*(int *)user != FAR || frame->hd.type != NGHTTP2_HEADERS || frame->headers.cat != NGHTTP2_HCAT_REQUEST)
    return 0;
  struct flow *f = find(frame->hd.stream_id);
  if (!f) return 0;
  arrive(f);
  nghttp2_nv status[] = {{(uint8_t *)":status", (uint8_t *)"200", 7, 3, NGHTTP2_NV_FLAG_NONE}};
  nghttp2_data_provider2 provider = {.read_callback = source};
  return nghttp2_submit_response2(s, frame->hd.stream_id, status, 1, &provider);
}

static int gone(nghttp2_session *s, int32_t id, uint32_t code, void *user) {
  (void)s, (void)code;
  struct flow *f = find(id);
  if (f && *(int *)user == NEAR) shut(f);
  return 0;
}

static void start(int side) {
  nghttp2_session_callbacks *cb;
  nghttp2_session_callbacks_new(&cb);
  nghttp2_session_callbacks_set_on_data_chunk_recv_callback(cb, chunk);
  nghttp2_session_callbacks_set_on_frame_recv_callback(cb, request);
  nghttp2_session_callbacks_set_on_stream_close_callback(cb, gone);
  nghttp2_option *opt;
  nghttp2_option_new(&opt);
  nghttp2_option_set_no_auto_window_update(opt, 1);  // see mux/README.md "Fairness"
  nghttp2_option_set_no_closed_streams(opt, 1);
  nghttp2_session **s = &SESSIONS[side];
  int rv = side == NEAR ? nghttp2_session_client_new2(s, cb, &WHICH[side], opt)
                        : nghttp2_session_server_new2(s, cb, &WHICH[side], opt);
  if (rv) fail("session: %s", nghttp2_strerror(rv));
  nghttp2_option_del(opt);
  nghttp2_session_callbacks_del(cb);
  nghttp2_settings_entry settings[] = {
      {NGHTTP2_SETTINGS_INITIAL_WINDOW_SIZE, (uint32_t)P.window},
      {NGHTTP2_SETTINGS_MAX_CONCURRENT_STREAMS, (uint32_t)limit()},  // see mux/README.md "Fairness"
  };
  nghttp2_submit_settings(*s, NGHTTP2_FLAG_NONE, settings, 2);
  nghttp2_session_set_local_window_size(*s, NGHTTP2_FLAG_NONE, 0, CONNECTION);
}

static int up(void) { return 1; }

static void stop(int side) { nghttp2_session_del(SESSIONS[side]); }

static int64_t begin(void) {
  nghttp2_nv nv[] = {
      {(uint8_t *)":method", (uint8_t *)"POST", 7, 4, NGHTTP2_NV_FLAG_NONE},
      {(uint8_t *)":scheme", (uint8_t *)"http", 7, 4, NGHTTP2_NV_FLAG_NONE},
      {(uint8_t *)":path", (uint8_t *)"/", 5, 1, NGHTTP2_NV_FLAG_NONE},
      {(uint8_t *)":authority", (uint8_t *)"peer", 10, 4, NGHTTP2_NV_FLAG_NONE},
  };
  nghttp2_data_provider2 provider = {.read_callback = source};
  int32_t id = nghttp2_submit_request2(SESSIONS[NEAR], NULL, nv, 4, &provider, NULL);
  if (id < 0) fail("submit_request2: %s", nghttp2_strerror(id));
  return id;
}

static void resume(int side, struct flow *f) { nghttp2_session_resume_data(SESSIONS[side], (int32_t)f->id); }

static ssize_t emit(int side, const uint8_t **out) {
  nghttp2_ssize n = nghttp2_session_mem_send2(SESSIONS[side], out);
  if (n < 0) fail("mem_send2: %s", nghttp2_strerror((int)n));
  return n;
}

static void feed(int side, const uint8_t *data, size_t len) {
  nghttp2_ssize n = nghttp2_session_mem_recv2(SESSIONS[side], data, len);
  if (n < 0) fail("mem_recv2: %s", nghttp2_strerror((int)n));
}

const struct lib NGHTTP2 = {"nghttp2", version, slot, start, up, stop, begin, resume, emit, feed};
