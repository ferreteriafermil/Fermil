#!/usr/bin/env bash
# Publica la carpeta _site en Cloudflare Pages y deja el resultado visible en GitHub.
PROYECTO="${PROYECTO:-ferreteria-fermil}"
if [ -z "$CLOUDFLARE_API_TOKEN" ] || [ -z "$CLOUDFLARE_ACCOUNT_ID" ]; then
  echo "::error title=Cloudflare::Faltan los secretos CLOUDFLARE_API_TOKEN o CLOUDFLARE_ACCOUNT_ID"; exit 1
fi
limpiar() { tr '\r\n' '  ' | sed -e 's/\x1b\[[0-9;]*m//g' -e 's/%/%25/g' | tail -c "${1:-800}"; }
npx --yes wrangler@4 pages project create "$PROYECTO" --production-branch=main > crear.log 2>&1 \
  && echo "::notice title=Cloudflare::Proyecto $PROYECTO creado" \
  || echo "Proyecto ya existía o no se pudo crear: $(limpiar 300 < crear.log)"
if npx --yes wrangler@4 pages deploy _site --project-name="$PROYECTO" --branch=main --commit-dirty=true > publicar.log 2>&1; then
  URL=$(grep -oE 'https://[a-z0-9.-]+\.pages\.dev' publicar.log | tail -1)
  echo "::notice title=Cloudflare::Página publicada ${URL}"
  tail -5 publicar.log
else
  echo "::error title=Cloudflare::$(limpiar 300 < crear.log) || $(limpiar 900 < publicar.log)"
  exit 1
fi
