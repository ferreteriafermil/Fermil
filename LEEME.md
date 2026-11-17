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
| CORREO_USUARIO | Gmail que envía el resumen diario de precios (administracionfermil@gmail.com) |
| CORREO_CLAVE | Contraseña de aplicación de ese Gmail (16 letras) |
| CORREOS_MAYORISTAS | Correos de los mayoristas: `Manuel Pérez <correo>, Leonardo Rojas <correo>, Noel Villavicencio <correo>` |

En `nube.json` van la Project URL y la Publishable key de Supabase: son públicas por diseño.

## Resumen diario de precios por correo
En la última corrida del día (7:00 p. m.) el robot envía un solo correo a cada mayorista con los precios al
mayor que subieron y bajaron ese día. Para probarlo ya: Actions → **Sincronizar con PLADE** → **Run workflow**
→ marcar "Enviar ya el resumen de precios por correo".

## Flyers y catálogos (panel del mayorista)
- **Crear flyer**: el mayorista busca un producto, escoge su precio (al mayor, con sus descuentos o los de un
  cliente), una etiqueta (Promoción, Precio especial, Aprovecha u otra) y el tamaño (vertical o cuadrado).
  Lo descarga o lo comparte directo a WhatsApp.
- **Catálogo PDF**: escoge categorías, nombre del cliente y precio. Sale con fotos, su nombre y WhatsApp,
  y dice que es válido solo el día en que se crea.

## Correr el robot a mano
Actions → **Sincronizar con PLADE** → **Run workflow**.
La primera corrida tarda de 2 a 3 horas porque baja todas las fotos; si no termina, sigue en la próxima.

## Si algo falla
- Corrida en rojo: abrir la corrida y leer el último paso con error.
- "No se pudo entrar a PLADE": revisar PLADE_USUARIO y PLADE_CLAVE.
- "Solo llegaron N productos": PLADE respondió incompleto; la página no se toca y se reintenta en 2 horas.

## Panel de tabulaciones (administración de fletes)
Un código aparte (`ADMIN-XXXX-XXXX`, tabla `tabulador_admins` en Supabase) abre el panel administrativo en
**Mayoristas → código**. No ve lo mismo que un mayorista: abre la calculadora de fletes.
- **Calcular viaje**: vendedor, camión, chofer y paradas en orden. En cada parada se escriben los códigos de los
  productos y la cantidad: el precio al mayor y el peso salen solos (peso de la ficha de PLADE). Da km, días,
  ocupación, costo del flete, venta mínima y si el viaje se aprueba. Compara todos los camiones y marca el más barato
  que aprueba. Imprime la orden en blanco y negro (o PDF).
- **Tabulador**: venta mínima por pueblo para camión pequeño, mediano y gandola.
- **Lugares y km**: para un pueblo nuevo se pegan sus coordenadas de Google Maps y los km por carretera hasta todos los
  demás se miden solos (OpenStreetMap/OSRM). Después: **Guardar cambios**.
- **Costos y flota**: gasoil, viáticos, hotel, topes, peajes, camiones y choferes. La tasa BCV es la del día de PLADE.
- Los cálculos son los mismos del Excel `SISTEMA_ERP_FERMIL_TABULACIONES_ADMINISTRATIVO`.
- El robot baja el peso de cada producto poco a poco (25 minutos por corrida) y lo guarda en `pesos_plade.json`.
- Para activarlo hay que correr una vez el archivo privado `supabase-actualizacion-2-CON-DATOS.sql` (lo tiene la administración; trae costos y nómina, por eso no está aquí). Al final muestra el código de administración.
