mux:
  pkg.installed:
    - pkgs:
      - python3
      - ca-certificates
      - build-essential

apt:
  cmd.run:
    - name: apt-get clean # see the repo's README "Runners": a cached image carries no downloaded packages
    - require:
      - pkg: mux

harnesses:
  cmd.run:
    - name: /var/lib/bencher/runner/build {{ grains['bencher']['inputs'] }} {{ salt['pillar.get']('bencher:phase', 'run') }}
    - require:
      - pkg: mux
