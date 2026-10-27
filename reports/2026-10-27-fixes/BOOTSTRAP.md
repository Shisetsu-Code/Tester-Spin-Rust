# Evidencia de arranque y bloqueos restantes

Observación de páginas públicas y demos en [Actions 40551803690](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40551803690). La observación de bootstrap no se contabiliza como un giro correcto ni modifica los resultados de la campaña.

## ELK: arranque resuelto y validado

Las fichas oficiales tenían enlaces `href` y `data-src` que podían discrepar. El código del sitio y su loader seleccionan `href`. La preparación nueva valida esa relación en recursos frescos, además de canonical, título, host, modo demo y símbolo, y bloquea cualquier URL anterior si falla la preparación.

En [Actions 40557863852](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40557863852), Arcanum, Ashoka y Ashoka Eternal completaron el arranque CAPI y dos rondas base cada uno con liquidación verificada. Los tres siguen PARCIAL porque el servidor anuncia cinco modos adicionales `X01–X05` que todavía faltan ejecutar y cubrir. El siguiente trabajo de ELK ya es sobre esos modos; la identidad demo dejó de ser el bloqueo.

## Play'n GO

Las tres páginas oficiales enlazan un `ContainerLauncher` con `practice=1`. La secuencia observada llega a metadata, prelaunch, registro/login, configuración y conexión a `gamehub`. El servidor confirma moneda DEMO y jurisdicción ZZ.

| Juego | gid | gameId | Recurso versionado |
| --- | --- | ---: | --- |
| *NSYNC Pop | nsyncpop | 629 | 1.6.1-nsyncpop.446 |
| 1001 Mystery Genie Fortunes | geniefortunes | 985 | 1.9.0-geniefortunes.399 |
| 13th Trial Hercules Abyssways | herculesabyssways | 1025 | 1.2.1-herculesabyssways.354 |

Los tres bundles públicos estáticos se recuperaron sin abrir sesiones de juego y sus SHA-256 coinciden con los registrados en Actions:

- `28e932850920c739d9bf7e94cd1e67964b7bb211ad691590d87a3d0aa1c3f21e`
- `a2fdba964caf89d0671eb8d1ec3f2f2a318097f20b6ca7a515707d97e680be05`
- `66dc5d14c2c6eb0924640ebfc07b35b9f3dd528144adc3254ac3aa64dbaed151`

El cliente liga `NEW_GAME` a 104 y `SPIN` a 1. El orden del giro es monedas, líneas y denominación; su coste es el producto de esos tres valores. Un cuarto argumento `1` depende de `_confirmCollect`. Es evidencia del serializador, todavía insuficiente para afirmar que una cotización concreta sea válida o que una respuesta liquide la ronda.

La captura no contiene una inicialización 104 con sus dominios 52/54, ni un giro/cierre de estos juegos. Las respuestas WebSocket binarias tampoco quedaron conservadas por el observador. El adaptador permanece detenido por `CAPTURE_BOUND_PRACTICE_PROFILE_REQUIRED`. Para habilitarlo faltan cotización actual, condición de collect, firma terminal y conciliación de saldo. La comparación existente de líneas y denominación contra una fila de denominaciones debe corregirse junto con ese binding; no constituye una prueba de líneas válidas.

## Relax

En AgroCulture, Ancient Tumble y Atlantis Crush, `Try Game` abrió una confirmación de edad. No se observó iframe de juego, login ni inicialización. La ficha contiene enlaces de launcher, pero por sí sola no prueba el contrato del engine, la versión vigente ni una cotización. No se omitió esa confirmación.

El adaptador sigue esperando `OBSERVED_DEMO_BOOTSTRAP_CONTRACT_REQUIRED`. Después de completar la confirmación en el sitio, hace falta observar y enlazar el launcher oficial con el login demo, el código interno del juego y la versión. Aun resuelto el arranque, siguen pendientes inventario pagado y continuaciones.

## Playson

Las tres páginas mostraron frames de Cloudflare Turnstile. No se obtuvo el bootstrap del juego. El contrato de endpoint, identidad TEST, versión y cotización base sigue sin demostrarse en un checkout limpio. No se intentó resolver ni eludir el desafío.

## Games Global

La observación de la lista pública no alcanzó un launcher de juego. En la campaña real, 12 Masks of Fire Drums queda bloqueado por una continuación/elección sin binding; 3 Lucky Rainbows Action Boost Max y 333 Boom Banks POWER COMBO no aportan la confirmación de modo practice que exige el ejecutor. El control `PRACTICE_PLAY_REQUIRED` permanece activo.

## Pragmatic

La [observación específica 40552978574](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40552978574) quedó incompleta: Chests aportó un resumen y cliente, Rat sólo parte de los recursos y Sweet no quedó capturado. El procesamiento síncrono de capturas excedió la ventana de observación prevista; no se interpreta la ausencia de archivos como ausencia de funciones del juego.

En Chests se pudo trazar `bls` ausente → configuración de BetLevel nula → request de giro sin `bl`. No aparece una bandera explícita de ante ausente y falta demostrar el inventario completo de componentes activos. Por eso no se declara vacío el dominio de ante. En Sweet faltan además sus datos actuales de cliente/init para resolver los dos dominios pagados.

## Integridad de las capturas de código

Se encontró un defecto del exportador: una propiedad JavaScript `cookie:` se interpretaba como una cabecera HTTP y eliminaba el resto de una línea minificada. Se acotó esa redacción a posiciones de cabecera y se preservó el saneado de credenciales en propiedades JavaScript. Los tests comprueban a la vez conservación del código posterior y eliminación de cookies, tokens, sesiones, contraseñas y secretos.

Los hashes originales identifican los bytes descargados, no los cuerpos transformados por el sanitizador. Para el análisis estático que requería código íntegro se recuperaron únicamente los assets públicos exactos y se verificó su hash antes de leerlos. No se reutilizaron credenciales ni sesiones capturadas.
