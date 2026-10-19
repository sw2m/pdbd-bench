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

oracles:
  cmd.run:
    - name: /var/lib/bencher/runner/oracles '{{ pins | json }}'
    - require:
      - pkg: socat
