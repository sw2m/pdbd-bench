using System.Diagnostics;
using System.Globalization;
using System.Net;
using System.Net.Sockets;
using System.Runtime.InteropServices;
using System.Text.Json;
using Nerdbank.Streams;

if (args is ["version", "nerdbank"])
{
    Console.WriteLine(typeof(MultiplexingStream).Assembly
        .GetCustomAttributes(typeof(System.Reflection.AssemblyInformationalVersionAttribute), false)
        .OfType<System.Reflection.AssemblyInformationalVersionAttribute>()
        .First().InformationalVersion.Split('+')[0]);
    return 0;
}
if (args is not ["nerdbank", var scenario, var raw])
{
    Console.Error.WriteLine("peer: usage: peer nerdbank <scenario> <params json> | peer version nerdbank");
    return 2;
}
var p = JsonSerializer.Deserialize<Params>(raw, new JsonSerializerOptions { PropertyNameCaseInsensitive = true })!;
try
{
    Console.WriteLine(JsonSerializer.Serialize(await Bench.Run(scenario, p)));
    return 0;
}
catch (Exception e)
{
    Console.Error.WriteLine($"peer: nerdbank {scenario}: {e}");
    return 2;
}

// see mux/README.md "Scenarios"
sealed record Params(
    int Window, int Chunk, long Bulk, int Flows, int Message, int Pings, int Warm, int Load, int Churn, int Idle,
    double Timeout);

sealed class Outcome
{
    public Dictionary<string, double> values { get; init; } = [];
    public string verdict { get; init; } = "ok";
}

static class Native
{
    [StructLayout(LayoutKind.Sequential)]
    struct Rusage
    {
        public long UserSec, UserMicro, SystemSec, SystemMicro;
        public long MaxRss, Ixrss, Idrss, Isrss, Minflt, Majflt, Nswap, Inblock, Oublock, Msgsnd, Msgrcv, Nsignals, Nvcsw, Nivcsw;
    }

    [DllImport("libc", SetLastError = true)]
    static extern int getrusage(int who, out Rusage usage);

    public static double Cpu()
    {
        if (getrusage(0, out var u) != 0)
        {
            throw new InvalidOperationException($"getrusage: errno {Marshal.GetLastWin32Error()}");
        }
        return (u.UserSec + u.SystemSec) * 1e3 + (u.UserMicro + u.SystemMicro) / 1e3;
    }

    public static double Status(string field)
    {
        foreach (var line in File.ReadAllLines("/proc/self/status"))
        {
            if (line.StartsWith(field + ":", StringComparison.Ordinal))
            {
                return double.Parse(line[(field.Length + 1)..].Trim().Split(' ')[0], CultureInfo.InvariantCulture) * 1024;
            }
        }
        throw new InvalidOperationException($"/proc/self/status has no {field}");
    }

    public static double Rss()
    {
        GC.Collect(2, GCCollectionMode.Forced, blocking: true, compacting: true);
        GC.WaitForPendingFinalizers();
        GC.Collect(2, GCCollectionMode.Forced, blocking: true, compacting: true);
        return Status("VmRSS");
    }
}

sealed class Session : IAsyncDisposable
{
    readonly MultiplexingStream near;
    readonly MultiplexingStream far;
    int opened;
    int accepted;

    Session(MultiplexingStream near, MultiplexingStream far) => (this.near, this.far) = (near, far);

    public static async Task<Session> NewAsync(Params p)
    {
        var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        var dial = new TcpClient { NoDelay = true };
        var connect = dial.ConnectAsync(IPAddress.Loopback, ((IPEndPoint)listener.LocalEndpoint).Port);
        var answer = await listener.AcceptTcpClientAsync();
        await connect;
        listener.Stop();
        answer.NoDelay = true;
        var options = new MultiplexingStream.Options
        {
            ProtocolMajorVersion = 3,
            DefaultChannelReceivingWindowSize = p.Window,
        };
        var near = MultiplexingStream.CreateAsync(dial.GetStream(), options);
        var far = MultiplexingStream.CreateAsync(answer.GetStream(), options);
        return new Session(await near, await far);
    }

    public Task<MultiplexingStream.Channel> Offer() =>
        this.near.OfferChannelAsync(Interlocked.Increment(ref this.opened).ToString(CultureInfo.InvariantCulture));

    public async Task<(MultiplexingStream.Channel, long)> Take()
    {
        var name = Interlocked.Increment(ref this.accepted).ToString(CultureInfo.InvariantCulture);
        var channel = await this.far.AcceptChannelAsync(name);
        return (channel, Stopwatch.GetTimestamp());
    }

    public async Task<Stream> Open() => (await this.Offer()).AsStream();

    public async Task<(Stream, long)> Accept()
    {
        var (channel, at) = await this.Take();
        return (channel.AsStream(), at);
    }

    // see mux/README.md "Comparators"
    public static async Task Finish(MultiplexingStream.Channel c)
    {
        await c.Output.CompleteAsync();
        while (true)
        {
            var r = await c.Input.ReadAsync();
            c.Input.AdvanceTo(r.Buffer.End);
            if (r.IsCompleted)
            {
                break;
            }
        }
        c.Dispose();
    }

    public async ValueTask DisposeAsync()
    {
        await this.near.DisposeAsync();
        await this.far.DisposeAsync();
    }
}

sealed class Bench(Session s, Params p)
{
    readonly byte[] data = Enumerable.Repeat((byte)0x5a, p.Chunk).ToArray();

    // see mux/README.md "Statistics"
    public static async Task<Outcome> Run(string scenario, Params p)
    {
        if (scenario == "isolation")
        {
            await Once("calm", p); // see mux/README.md "Statistics"
        }
        await Once(scenario, p);
        double? calm = null;
        if (scenario == "isolation")
        {
            var baseline = await Once("calm", p);
            if (baseline.verdict != "ok")
            {
                throw new TimeoutException("the calm baseline missed the deadline");
            }
            calm = baseline.values["MiB/s"];
            await File.WriteAllTextAsync("/proc/self/clear_refs", "5");
        }
        var before = Native.Cpu();
        var outcome = await Once(scenario, p);
        outcome.values["cpu ms"] = Native.Cpu() - before;
        if (calm is { } c && outcome.verdict == "ok")
        {
            outcome.values["calm MiB/s"] = c;
            outcome.values["ratio"] = outcome.values["MiB/s"] / c;
        }
        return outcome;
    }

    static async Task<Outcome> Once(string scenario, Params p)
    {
        await using var s = await Session.NewAsync(p);
        var b = new Bench(s, p);
        return scenario switch
        {
            "bulk" => await b.Bulk(),
            "flows" => await b.Flows(),
            "isolation" => await b.Isolation(true),
            "calm" => await b.Isolation(false),
            "pingpong" => await b.Pingpong(0),
            "loaded" => await b.Pingpong(p.Load),
            "churn" => await b.Churn(),
            "idle" => await b.Idle(),
            _ => throw new ArgumentException($"unsupported scenario {scenario}"),
        };
    }

    static double Mib(long bytes, TimeSpan spent) => bytes / (double)(1 << 20) / spent.TotalSeconds;

    async Task Fill(Stream f, long want)
    {
        for (long sent = 0; sent < want;)
        {
            var n = (int)Math.Min(this.data.Length, want - sent);
            await f.WriteAsync(this.data.AsMemory(0, n));
            sent += n;
        }
        await f.FlushAsync();
    }

    async Task<long> Drain(Stream f, long want)
    {
        var buf = new byte[this.data.Length];
        for (long got = 0; got < want;)
        {
            var n = await f.ReadAsync(buf);
            if (n == 0)
            {
                throw new EndOfStreamException($"EOF after {got} of {want} bytes");
            }
            got += n;
        }
        return Stopwatch.GetTimestamp();
    }

    async Task<(Stream[] Outs, Stream[] Ins)> Opened(int n)
    {
        var accepting = Task.Run(async () =>
        {
            var ins = new Stream[n];
            for (var i = 0; i < n; i++)
            {
                (ins[i], _) = await s.Accept();
                var echo = new byte[1];
                await ins[i].ReadExactlyAsync(echo);
                await ins[i].WriteAsync(echo);
                await ins[i].FlushAsync();
            }
            return ins;
        });
        var outs = new Stream[n];
        for (var i = 0; i < n; i++)
        {
            outs[i] = await s.Open();
            await outs[i].WriteAsync(this.data.AsMemory(0, 1));
            await outs[i].FlushAsync();
        }
        var accepted = await accepting;
        foreach (var f in outs)
        {
            await f.ReadExactlyAsync(new byte[1]);
        }
        return (outs, accepted);
    }

    public async Task<Outcome> Bulk()
    {
        var (outs, ins) = await this.Opened(1);
        var start = Stopwatch.GetTimestamp();
        var drained = this.Drain(ins[0], p.Bulk);
        await this.Fill(outs[0], p.Bulk);
        var end = await drained;
        return new Outcome { values = { ["MiB/s"] = Mib(p.Bulk, Stopwatch.GetElapsedTime(start, end)) } };
    }

    async Task<(long Start, long[] Ends)?> Spread(Stream[] outs, Stream[] ins, long share)
    {
        var start = Stopwatch.GetTimestamp();
        var readers = ins.Select(f => Task.Run(() => this.Drain(f, share))).ToArray();
        var writers = outs.Select(f => Task.Run(() => this.Fill(f, share))).ToArray();
        var all = Task.WhenAll(Task.WhenAll(readers), Task.WhenAll(writers));
        if (await Task.WhenAny(all, Task.Delay(TimeSpan.FromSeconds(p.Timeout))) != all)
        {
            return null;
        }
        await all;
        return (start, readers.Select(r => r.Result).ToArray());
    }

    static (double Jain, double Slowest) Fairness(double[] rates)
    {
        var sum = rates.Sum();
        var sorted = rates.Order().ToArray();
        return (sum * sum / (rates.Length * rates.Sum(r => r * r)), sorted[0] / sorted[sorted.Length / 2]);
    }

    public async Task<Outcome> Flows()
    {
        var share = p.Bulk / p.Flows;
        var (outs, ins) = await this.Opened(p.Flows);
        var spread = await this.Spread(outs, ins, share) ?? throw new TimeoutException("flows missed the deadline");
        var rates = spread.Ends.Select(e => Mib(share, Stopwatch.GetElapsedTime(spread.Start, e))).ToArray();
        var (jain, slowest) = Fairness(rates);
        var last = spread.Ends.Max();
        return new Outcome
        {
            values =
            {
                ["MiB/s"] = Mib(share * p.Flows, Stopwatch.GetElapsedTime(spread.Start, last)),
                ["jain"] = jain,
                ["slowest"] = slowest,
            },
        };
    }

    public async Task<Outcome> Isolation(bool stalled)
    {
        var begin = Native.Status("VmRSS");
        var share = p.Bulk / p.Flows;
        var (outs, ins) = await this.Opened(p.Flows);
        if (stalled)
        {
            _ = Task.Run(() => this.Fill(outs[0], share)); // see mux/README.md "Scenarios"
        }
        var spread = await this.Spread(outs[1..], ins[1..], share);
        if (spread is not { } done)
        {
            return new Outcome { verdict = "err" };
        }
        var last = done.Ends.Max();
        return new Outcome
        {
            values =
            {
                ["MiB/s"] = Mib(share * (p.Flows - 1), Stopwatch.GetElapsedTime(done.Start, last)),
                ["peak B"] = Native.Status("VmHWM") - begin,
            },
        };
    }

    static Dictionary<string, double> Percentiles(List<double> micros, string prefix)
    {
        micros.Sort();
        double At(double q) => micros[(int)(q * (micros.Count - 1))];
        var out_ = new Dictionary<string, double> { [$"{prefix}p50 µs"] = At(0.50), [$"{prefix}p99 µs"] = At(0.99) };
        if (prefix.Length == 0)
        {
            out_["p999 µs"] = At(0.999);
        }
        return out_;
    }

    public async Task<Outcome> Pingpong(int load)
    {
        var (outs, ins) = await this.Opened(1 + load);
        using var stop = new CancellationTokenSource();
        for (var i = 1; i <= load; i++)
        {
            var (o, f) = (outs[i], ins[i]);
            _ = Task.Run(async () =>
            {
                var buf = new byte[this.data.Length];
                while (await f.ReadAsync(buf) > 0)
                {
                }
            });
            _ = Task.Run(async () =>
            {
                while (!stop.IsCancellationRequested)
                {
                    await o.WriteAsync(this.data);
                }
            });
        }
        _ = Task.Run(async () =>
        {
            var echo = new byte[p.Message];
            while (true)
            {
                await ins[0].ReadExactlyAsync(echo);
                await ins[0].WriteAsync(echo);
                await ins[0].FlushAsync();
            }
        });
        var buf = new byte[p.Message];
        var trips = new List<double>(p.Pings);
        for (var i = 0; i < p.Warm + p.Pings; i++)
        {
            var start = Stopwatch.GetTimestamp();
            await outs[0].WriteAsync(this.data.AsMemory(0, p.Message));
            await outs[0].FlushAsync();
            await outs[0].ReadExactlyAsync(buf);
            if (i >= p.Warm)
            {
                trips.Add(Stopwatch.GetElapsedTime(start).TotalMicroseconds);
            }
        }
        stop.Cancel();
        return new Outcome { values = Percentiles(trips, "") };
    }

    public async Task<Outcome> Churn()
    {
        var arrivals = System.Threading.Channels.Channel.CreateUnbounded<long>();
        var serving = Task.Run(async () =>
        {
            for (var i = 0; i < p.Churn; i++)
            {
                var (c, at) = await s.Take();
                arrivals.Writer.TryWrite(at);
                _ = Task.Run(async () =>
                {
                    var f = c.AsStream();
                    var one = new byte[1];
                    await f.ReadExactlyAsync(one);
                    await f.WriteAsync(one);
                    await f.FlushAsync();
                    await Session.Finish(c);
                });
            }
        });
        var waits = new List<double>(p.Churn);
        var one = new byte[1];
        var start = Stopwatch.GetTimestamp();
        for (var i = 0; i < p.Churn; i++)
        {
            var opened = Stopwatch.GetTimestamp();
            var c = await s.Offer();
            var f = c.AsStream();
            await f.WriteAsync(this.data.AsMemory(0, 1));
            await f.FlushAsync();
            var at = await arrivals.Reader.ReadAsync();
            waits.Add(Stopwatch.GetElapsedTime(opened, at).TotalMicroseconds);
            await f.ReadExactlyAsync(one);
            await Session.Finish(c);
        }
        var spent = Stopwatch.GetElapsedTime(start);
        await serving;
        var values = Percentiles(waits, "open ");
        values["cycles/s"] = p.Churn / spent.TotalSeconds;
        return new Outcome { values = values };
    }

    public async Task<Outcome> Idle()
    {
        var before = Native.Rss();
        var (outs, ins) = await this.Opened(p.Idle);
        await Task.Delay(50); // see mux/README.md "Scenarios"
        var after = Native.Rss();
        GC.KeepAlive(outs);
        GC.KeepAlive(ins);
        return new Outcome { values = { ["B/flow"] = (after - before) / p.Idle } };
    }
}
