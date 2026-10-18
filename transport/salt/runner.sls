{% set pins = salt['pillar.get']('bencher:params:pins', {}) %}
transport:
  pkg.installed:
    - pkgs:
      - socat
      - iperf3
      - iproute2
      - iputils-ping
      - jq
      - curl
      - ca-certificates
      - build-essential
      - pkg-config
      - libssl-dev
      - libpcap-dev

ppp:
  kmod.present:
    - mods:
      - ppp_generic
      - ppp_async
      - tun

pppd:
  cmd.run:
    - name: /var/lib/bencher/runner/pppd {{ pins.get('pppd', '') }}
    - require:
      - pkg: transport
