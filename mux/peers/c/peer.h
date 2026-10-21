// see mux/README.md "Comparators"
#ifndef PEER_H
#define PEER_H

#include <stddef.h>
#include <stdint.h>
#include <sys/types.h>

#define CONNECTION (1 << 30) // see mux/README.md "Fairness"

struct params {
  long window, chunk, bulk, flows, message, pings, warm, load, churn, idle;
  double timeout;
};

struct end {
  long pending, rx;
  int eof, queued, ended;
};

struct flow {
  int64_t id;
  struct end near, far;
  int stall, echo, close, accepted, closed;
  double opened, arrived, done;
  long want;
};

enum { NEAR, FAR };

struct lib {
  const char *name;
  const char *(*version)(void);
  size_t (*slot)(int64_t id);
  void (*start)(int side);
  int (*up)(void);
  void (*stop)(int side);
  int64_t (*open)(void);
  void (*resume)(int side, struct flow *f);
  ssize_t (*send)(int side, const uint8_t **out);
  void (*recv)(int side, const uint8_t *data, size_t len);
};

extern struct params P;
extern uint8_t *DATA;
extern const struct lib NGHTTP2, DWNX;

void fail(const char *format, ...);
double now(void);
long limit(void);
struct end *end(int side, struct flow *f);
struct flow *find(int64_t id);
size_t take(int side, struct flow *f, size_t max, int *fin);
int got(int side, struct flow *f, size_t len);
void arrive(struct flow *f);
void shut(struct flow *f);

#endif
