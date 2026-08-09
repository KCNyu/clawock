#!/usr/bin/env bash
# Quick portfolio check through the two live market pipelines.
set -euo pipefail

cd "$(dirname "$0")"
clawock analyze-hk
clawock analyze-us
