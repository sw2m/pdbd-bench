import fs from 'node:fs'
import net from 'node:net'
import { performance } from 'node:perf_hooks'
import { logger } from '@libp2p/logger'
import { AbstractMultiaddrConnection, ipPortToMultiaddr } from '@libp2p/utils'
import { yamux } from '@libp2p/yamux'

// see mux/README.md "Build"
class Tcp extends AbstractMultiaddrConnection {
  constructor (socket, direction) {
    super({ remoteAddr: ipPortToMultiaddr(socket.remoteAddress, socket.remotePort), direction, log: logger('peer:tcp') })
    this.socket = socket
    socket.on('data', buf => { this.onData(buf) })
    socket.on('error', err => { this.abort(err) })
    socket.once('close', () => { this.onTransportClosed() })
    socket.on('drain', () => { this.safeDispatchEvent('drain') })
  }

  sendData (data) {
    let sentBytes = 0
    let canSendMore = true
    for (const buf of data) {
      sentBytes += buf.byteLength
      canSendMore = this.socket.write(buf)
      if (!canSendMore) break
    }
    return { sentBytes, canSendMore }
  }

  async sendClose () {
    if (!this.socket.destroyed) this.socket.destroySoon()
  }

  sendReset () { this.socket.destroy() }
  sendPause () { this.socket.pause() }
  sendResume () { this.socket.resume() }
}

class Flow {
  constructor (stream) {
    this.stream = stream
    this.received = 0
    this.keep = true
    this.kept = []
    this.keeping = 0
    this.waiters = []
    stream.addEventListener('message', event => {
      const bytes = event.data.subarray()
      this.received += bytes.byteLength
      if (this.keep) {
        this.kept.push(bytes)
        this.keeping += bytes.byteLength
      }
      for (const wake of this.waiters.splice(0)) wake()
    })
    stream.addEventListener('close', () => { for (const wake of this.waiters.splice(0)) wake() })
  }

  wait () { return new Promise(resolve => { this.waiters.push(resolve) }) }

  async write (buf) {
    if (this.stream.send(buf)) await new Promise(resolve => setImmediate(resolve))
    else await this.stream.onDrain()
  }

  async drain (want) {
    this.keep = false
    this.kept = []
    this.keeping = 0
    while (this.received < want) {
      if (this.stream.status !== 'open') throw new Error(`stream ${this.stream.status} after ${this.received} of ${want} bytes`)
      await this.wait()
    }
    return performance.now()
  }

  async read (n) {
    while (this.keeping < n) {
      if (this.stream.status !== 'open') throw new Error(`stream ${this.stream.status} with ${this.keeping} of ${n} bytes`)
      await this.wait()
    }
    const all = Buffer.concat(this.kept)
    this.kept = all.byteLength > n ? [all.subarray(n)] : []
    this.keeping -= n
    return all.subarray(0, n)
  }
}

class Session {
  static async create (p) {
    const server = net.createServer()
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
    const accepted = new Promise(resolve => server.once('connection', resolve))
    const near = net.connect(server.address().port, '127.0.0.1')
    await new Promise(resolve => near.once('connect', resolve))
    const far = await accepted
    server.close()
    near.setNoDelay(true)
    far.setNoDelay(true)
    const limit = Math.max(p.flows, p.load + 1, p.idle, p.churn) + 1 // see mux/README.md "Fairness"
    const factory = yamux({
      maxInboundStreams: limit,
      maxOutboundStreams: limit,
      enableKeepAlive: false,
      streamOptions: { initialStreamWindowSize: p.window, maxStreamWindowSize: p.window }
    })()
    const s = new Session()
    s.near = factory.createStreamMuxer(new Tcp(near, 'outbound'))
    s.far = factory.createStreamMuxer(new Tcp(far, 'inbound'))
    s.inbound = []
    s.waiting = []
    s.far.addEventListener('stream', event => {
      const flow = { flow: new Flow(event.detail), at: performance.now() }
      const wake = s.waiting.shift()
      if (wake) wake(flow)
      else s.inbound.push(flow)
    })
    s.sockets = [near, far]
    return s
  }

  async open () { return new Flow(await this.near.createStream()) }

  accept () {
    const ready = this.inbound.shift()
    return ready ? Promise.resolve(ready) : new Promise(resolve => this.waiting.push(resolve))
  }

  close () {
    for (const socket of this.sockets) socket.destroy()
  }
}

const mib = (bytes, ms) => bytes / (1 << 20) / (ms / 1e3)

function status (field) {
  const line = fs.readFileSync('/proc/self/status', 'utf8').split('\n').find(l => l.startsWith(field + ':'))
  if (!line) throw new Error(`/proc/self/status has no ${field}`)
  return Number(line.slice(field.length + 1).trim().split(/\s+/)[0]) * 1024
}

function rss () {
  globalThis.gc()
  globalThis.gc()
  return status('VmRSS')
}

function deadline (promise, seconds) {
  let timer
  const late = new Promise(resolve => { timer = setTimeout(() => resolve(null), seconds * 1e3) })
  return Promise.race([promise, late]).finally(() => clearTimeout(timer))
}

function percentiles (micros, prefix) {
  micros.sort((a, b) => a - b)
  const at = q => micros[Math.floor(q * (micros.length - 1))]
  const out = { [`${prefix}p50 µs`]: at(0.50), [`${prefix}p99 µs`]: at(0.99) }
  if (prefix === '') out['p999 µs'] = at(0.999)
  return out
}

class Bench {
  constructor (s, p) {
    this.s = s
    this.p = p
    this.data = Buffer.alloc(p.chunk, 0x5a)
  }

  async fill (flow, want) {
    for (let sent = 0; sent < want;) {
      const n = Math.min(this.data.byteLength, want - sent)
      await flow.write(this.data.subarray(0, n))
      sent += n
    }
  }

  async opened (n) {
    const accepting = (async () => {
      const ins = []
      for (let i = 0; i < n; i++) {
        const { flow } = await this.s.accept()
        await flow.write(await flow.read(1))
        ins.push(flow)
      }
      return ins
    })()
    const outs = []
    for (let i = 0; i < n; i++) {
      const flow = await this.s.open()
      await flow.write(this.data.subarray(0, 1))
      outs.push(flow)
    }
    const accepted = await accepting
    for (const flow of outs) await flow.read(1)
    return [outs, accepted]
  }

  async bulk () {
    const [outs, ins] = await this.opened(1)
    const start = performance.now()
    const primed = 1
    const want = primed + this.p.bulk
    const drained = ins[0].drain(want)
    await this.fill(outs[0], this.p.bulk)
    return { values: { 'MiB/s': mib(this.p.bulk, (await drained) - start) }, verdict: 'ok' }
  }

  async spread (outs, ins, share) {
    const start = performance.now()
    const ends = Promise.all(ins.map(f => f.drain(share + 1)))
    const sent = Promise.all(outs.map(f => this.fill(f, share)))
    const done = await deadline(Promise.all([ends, sent]), this.p.timeout)
    return done === null ? null : { start, ends: done[0] }
  }

  async flows () {
    const n = this.p.flows
    const share = Math.floor(this.p.bulk / n)
    const [outs, ins] = await this.opened(n)
    const spread = await this.spread(outs, ins, share)
    if (spread === null) throw new Error('flows missed the deadline')
    const rates = spread.ends.map(e => mib(share, e - spread.start))
    const sum = rates.reduce((a, b) => a + b, 0)
    const sorted = [...rates].sort((a, b) => a - b)
    const last = Math.max(...spread.ends)
    return {
      values: {
        'MiB/s': mib(share * n, last - spread.start),
        jain: sum * sum / (n * rates.reduce((a, r) => a + r * r, 0)),
        slowest: sorted[0] / sorted[Math.floor(n / 2)]
      },
      verdict: 'ok'
    }
  }

  async isolation (stalled) {
    const begin = status('VmRSS')
    const n = this.p.flows
    const share = Math.floor(this.p.bulk / n)
    const [outs, ins] = await this.opened(n)
    ins[0].stream.pause()
    if (stalled) this.fill(outs[0], share).catch(() => {}) // see mux/README.md "Scenarios"
    const spread = await this.spread(outs.slice(1), ins.slice(1), share)
    if (spread === null) return { values: {}, verdict: 'err' }
    const last = Math.max(...spread.ends)
    return {
      values: { 'MiB/s': mib(share * (n - 1), last - spread.start), 'peak B': status('VmHWM') - begin },
      verdict: 'ok'
    }
  }

  async pingpong (load) {
    const [outs, ins] = await this.opened(1 + load)
    let stop = false
    for (let i = 1; i <= load; i++) {
      ins[i].drain(Infinity).catch(() => {})
      ;(async () => { while (!stop) await outs[i].write(this.data) })().catch(() => {})
    }
    const message = this.p.message
    const near = outs[0]
    const far = ins[0]
    ;(async () => {
      for (;;) await far.write(await far.read(message))
    })().catch(() => {})
    const trips = []
    for (let i = 0; i < this.p.warm + this.p.pings; i++) {
      const start = performance.now()
      await near.write(this.data.subarray(0, message))
      await near.read(message)
      if (i >= this.p.warm) trips.push((performance.now() - start) * 1e3)
    }
    stop = true
    return { values: percentiles(trips, ''), verdict: 'ok' }
  }

  async churn () {
    const n = this.p.churn
    const arrivals = []
    const serving = (async () => {
      for (let i = 0; i < n; i++) {
        const { flow, at } = await this.s.accept()
        arrivals.push(at)
        ;(async () => {
          await flow.write(await flow.read(1))
          await flow.stream.close()
        })().catch(() => {})
      }
    })()
    const waits = []
    const start = performance.now()
    for (let i = 0; i < n; i++) {
      const opened = performance.now()
      const flow = await this.s.open()
      await flow.write(this.data.subarray(0, 1))
      await flow.read(1)
      waits.push((arrivals[i] - opened) * 1e3)
      await flow.stream.close()
    }
    const spent = performance.now() - start
    await serving
    return { values: { 'cycles/s': n / (spent / 1e3), ...percentiles(waits, 'open ') }, verdict: 'ok' }
  }

  async idle () {
    const before = rss()
    const [outs, ins] = await this.opened(this.p.idle)
    await new Promise(resolve => setTimeout(resolve, 50)) // see mux/README.md "Scenarios"
    const after = rss()
    this.held = [outs, ins]
    return { values: { 'B/flow': (after - before) / this.p.idle }, verdict: 'ok' }
  }
}

async function once (scenario, p) {
  const s = await Session.create(p)
  const b = new Bench(s, p)
  try {
    switch (scenario) {
      case 'bulk': return await b.bulk()
      case 'flows': return await b.flows()
      case 'isolation': return await b.isolation(true)
      case 'calm': return await b.isolation(false)
      case 'pingpong': return await b.pingpong(0)
      case 'loaded': return await b.pingpong(p.load)
      case 'churn': return await b.churn()
      case 'idle': return await b.idle()
      default: throw new Error(`unsupported scenario ${scenario}`)
    }
  } finally {
    s.close()
  }
}

// see mux/README.md "Statistics"
async function run (scenario, p) {
  if (scenario === 'isolation') await once('calm', p) // see mux/README.md "Statistics"
  await once(scenario, p)
  let calm = null
  if (scenario === 'isolation') {
    const baseline = await once('calm', p)
    if (baseline.verdict !== 'ok') throw new Error('the calm baseline missed the deadline')
    calm = baseline.values['MiB/s']
    fs.writeFileSync('/proc/self/clear_refs', '5')
  }
  const before = process.cpuUsage()
  const outcome = await once(scenario, p)
  const spent = process.cpuUsage(before)
  outcome.values['cpu ms'] = (spent.user + spent.system) / 1e3
  if (calm !== null && outcome.verdict === 'ok') {
    outcome.values['calm MiB/s'] = calm
    outcome.values.ratio = outcome.values['MiB/s'] / calm
  }
  return outcome
}

const args = process.argv.slice(2)
if (args.length === 2 && args[0] === 'version' && args[1] === 'libp2p-yamux') {
  const manifest = new URL('./node_modules/@libp2p/yamux/package.json', import.meta.url)
  console.log(JSON.parse(fs.readFileSync(manifest, 'utf8')).version)
  process.exit(0)
}
if (args.length !== 3 || args[0] !== 'libp2p-yamux') {
  console.error('peer: usage: peer libp2p-yamux <scenario> <params json> | peer version libp2p-yamux')
  process.exit(2)
}
try {
  console.log(JSON.stringify(await run(args[1], JSON.parse(args[2]))))
  process.exit(0)
} catch (err) {
  console.error(`peer: libp2p-yamux ${args[1]}: ${err.stack}`)
  process.exit(2)
}
