socat:
  pkg.installed:
    - pkgs:
      - python3
      - util-linux
      - ca-certificates
      - build-essential
      - libssl-dev
      - libreadline-dev
      - libwrap0-dev

apt:
  cmd.run:
    - name: apt-get clean # see README "Runners": a cached image carries no downloaded packages
    - require:
      - pkg: socat

oracles:
  cmd.run:
    - name: /var/lib/bencher/runner/oracles {{ grains['bencher']['inputs'] }}
    - require:
      - pkg: socat
