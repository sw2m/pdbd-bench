{% set pins = salt['pillar.get']('bencher:params:pins', {}) %}
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

pins:
  file.serialize:
    - name: /var/lib/bencher/pins.json
    - dataset: {{ pins | json }}
    - serializer: json

oracles:
  cmd.run:
    - name: /var/lib/bencher/runner/oracles /var/lib/bencher/pins.json
    - require:
      - pkg: socat
      - file: pins
