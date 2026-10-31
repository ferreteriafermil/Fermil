# Ferretería Fermil · página web que se actualiza sola

Cada 2 horas, de 7:00 a. m. a 7:00 p. m. (hora de Venezuela), un robot entra a PLADE, copia
precios, existencias, fotos y la tasa del día, y vuelve a publicar la página.

## Cómo funciona
| Pieza | Dónde vive | Qué hace |
|---|---|---|
| `robot/` | GitHub Actions | Entra a PLADE, arma el catálogo público y sube los precios al mayor a Supabase |
| `web/` | Cloudflare Pages | La página: catálogo, carrito, pedidos por WhatsApp, PDF, mayoristas y banners |
| `supabase.sql` | Supabase | Tablas privadas: precios al mayor, mayoristas y sus clientes, banners, administradora |
| `fotos/` | Este repositorio | Fotos de productos ya descargadas de PLADE (el robot agrega las nuevas) |
| `.github/workflows/sincronizar.yml` | GitHub | El horario del robot y la publicación |

Lo que nunca sale a la página pública: costos, utilidades, precio menor y precio al mayor.
El precio al mayor solo lo entrega Supabase a quien escribe un código válido.

## Secretos (Settings → Secrets and variables → Actions)
| Nombre | Valor |
|---|---|
| PLADE_URL | https://fermil.pladesoftware.com |
| PLADE_USUARIO | usuario de PLADE |
| PLADE_CLAVE | clave de PLADE |
| CLOUDFLARE_ACCOUNT_ID | Account ID de Cloudflare |
| CLOUDFLARE_API_TOKEN | token con permiso Cloudflare Pages: Edit |
| SUPABASE_URL | Project URL de Supabase |
| SUPABASE_SECRET | Secret key de Supabase (sb_secret_...) |

En `nube.json` van la Project URL y la Publishable key de Supabase: son públicas por diseño.

## Correr el robot a mano
Actions → **Sincronizar con PLADE** → **Run workflow**.
La primera corrida tarda de 2 a 3 horas porque baja todas las fotos; si no termina, sigue en la próxima.

## Si algo falla
- Corrida en rojo: abrir la corrida y leer el último paso con error.
- "No se pudo entrar a PLADE": revisar PLADE_USUARIO y PLADE_CLAVE.
- "Solo llegaron N productos": PLADE respondió incompleto; la página no se toca y se reintenta en 2 horas.
