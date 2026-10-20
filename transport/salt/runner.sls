transport:
  pkg.installed:
    - pkgs:
      - python3
      - socat
      - iperf3
      - iproute2
      - iputils-ping
      - ca-certificates
      - build-essential
      - pkg-config
      - libssl-dev
      - libpcap-dev

apt:
  cmd.run:
    - name: apt-get clean # see README "Runners": a cached image carries no downloaded packages
    - require:
      - pkg: transport

ppp:
  kmod.present:
    - mods:
      - ppp_generic
      - ppp_async
      - tun

pppd:
  cmd.run:
    - name: /var/lib/bencher/runner/pppd {{ grains['bencher']['inputs'] }}
    - require:
      - pkg: transport
