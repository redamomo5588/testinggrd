#!/usr/bin/env bash
# Builds hoot:local (Hootenanny 0.2.87 on CentOS 7) from hootenanny/run-base-release.
# glpk needs SuiteSparse AMD/COLAMD (libamd.so.2, libcolamd.so.2), which normally come from EPEL;
# they are compiled here from SuiteSparse v5.4.0 so no CentOS/EPEL mirror is needed.
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d sslibs ]; then
  rm -rf /tmp/SuiteSparse && git clone -q --depth 1 --branch v5.4.0 https://github.com/DrTimothyAldenDavis/SuiteSparse.git /tmp/SuiteSparse
  for d in SuiteSparse_config AMD COLAMD; do make -C /tmp/SuiteSparse/$d library >/dev/null; done
  mkdir sslibs && cp -a /tmp/SuiteSparse/lib/*.so* sslibs/
fi
cp "${CA_BUNDLE:-/root/.ccr/ca-bundle.crt}" ca-bundle.crt 2>/dev/null || : > ca-bundle.crt
docker build --network host --build-arg PROXY="${HTTPS_PROXY:-}" -t hoot:local .
docker run --rm hoot:local hoot version
