# Tester Spin Rust: correcciones y resultados comparables — 27/10/2026

**La última observación disponible de los mismos 72 juegos alcanza 19 OK, 29 PARCIAL, 9 ERROR y 15 SIN_EJECUTOR, frente a 11 OK, 37 PARCIAL, 9 ERROR y 15 SIN_EJECUTOR de la referencia inicial.** Son ocho juegos adicionales que cumplen los controles del motor: tres de 1Spin4Win, dos de Playtech y tres de Hacksaw.

El total de 19 OK combina la campaña principal con comprobaciones posteriores en sesiones nuevas: Hacksaw, ELK/RubyPlay y el diagnóstico final Yggdrasil. No es el resultado de una sola corrida. Hacksaw aporta los tres OK adicionales respecto de la campaña principal; ELK, RubyPlay y Yggdrasil permanecen PARCIAL. Los 19 OK se conservan en la última vista; las observaciones posteriores precisan los pasos acreditados y lo que falta, sin promover estados por una comparación offline.

## Qué se ejecutó y qué representa cada total

| Observación | OK | PARCIAL | ERROR | SIN_EJECUTOR | Procedencia |
| --- | ---: | ---: | ---: | ---: | --- |
| Referencia inicial, 72 juegos | 11 | 37 | 9 | 15 | [Informe original](../2026-10-27-actions/README.md) |
| Nueva campaña principal, los mismos 72 juegos | 16 | 29 | 12 | 15 | [Actions 40553999461](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40553999461), commit `f5d9db2a4734fa5bebf7039fc614ea4fb644da65` |
| Última observación por juego, incorporando comprobaciones posteriores | **19** | **29** | **9** | **15** | Campaña principal + [Hacksaw](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40554710711), [ELK/RubyPlay](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40557863852) y [Yggdrasil](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40561470969) |

La campaña principal seleccionó tres registros verificados por proveedor, sin selección aleatoria. Se conserva la misma cohorte por `provider + slug`: 24 proveedores y 72 títulos. La vista más reciente contiene **57 payloads finales** del motor; los otros 15 títulos corresponden a los cinco proveedores cuyo registro activo sólo ofrece catálogo. En esa vista, **36 juegos tienen intentos registrados y se acreditan 70 muestras base completas**. Descubrir un título o producir un resultado de preparación no se contabiliza como haber ejecutado un giro.

Se solicitaron dos muestras por ruta, timeout de request de 30 segundos y límite por juego de 240 segundos. `--spins 2` no significa que el motor deba hacer únicamente dos giros base: puede ejecutar compras, antebets, continuaciones y probes de retorno. Los estados proceden del payload automático final persistido; no se usan aprobaciones manuales ni se convierten inventarios UNKNOWN en cero.

Los datos que sostienen cada vista están separados:

- **Última observación por juego:** [latest-games.csv](latest-games.csv) y [latest-games.json](latest-games.json).
- **Campaña principal sin sustituir resultados:** [games.csv](games.csv) y [games.json](games.json).
- **Compilación y pruebas:** [verification.json](verification.json).
- **Comprobación específica de Hacksaw:** [hacksaw-followup-verification.json](hacksaw-followup-verification.json).
- **Diagnóstico final Yggdrasil y comparación con el anterior:** [YGGDRASIL.md](YGGDRASIL.md).
- **Cambios de implementación:** [IMPLEMENTATION.md](IMPLEMENTATION.md).
- **Capturas de arranque y límites:** [BOOTSTRAP.md](BOOTSTRAP.md).

Cada fila de los JSON conserva el run, commit y artefacto de origen. Esta separación permite comprobar los resultados nuevos y consultar los fallos anteriores.

## Los ocho nuevos OK

| Familia | Juegos que pasan de PARCIAL a OK frente a la referencia | Cambio que permitió acreditarlos |
| --- | --- | --- |
| 1Spin4Win | Cash'n Fruits 40; Golden Joker Halloween; Lucky Legion Fortune | Declaraciones efectivas del cliente, con herencia y orden de asignación comprobados. El ante legado de Cash'n Fruits queda enlazado a su selector y coste; los ceros de los otros títulos tienen evidencia explícita del cliente. |
| Playtech | 1 of a Kind™; 15 Diamonds™ | Binding del coste de líneas y del selector default hasta el comando GPAS. Se verifican la ejecución y el cierre; no se decide por una lista de UUID o por el precio aislado. |
| Hacksaw Gaming | Dr Zappo; Le Vampire; Wicked Grin | Planificación de las dos muestras exigidas por ruta y opción. La comprobación posterior ejecutó las opciones y conservó los gates de dinero, cierre y retorno. |

### Por qué Hacksaw tiene una segunda observación

En la campaña principal, los tres títulos Hacksaw terminaron ERROR al recibir HTTP 404 en el primer SPIN. La [comprobación 40554710711](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40554710711) abrió sesiones nuevas y obtuvo tres OK. El árbol `engine` es idéntico en ambas corridas: `51a8144169bd8ac34ae1110af5b87497fe000418`. La segunda observación conserva su procedencia propia y no reintenta un identificador de ronda de estado incierto.

La verificación de los artefactos acredita 32 rondas de muestra cerradas y seis rondas de retorno en esa comprobación. **La causa de los 404 anteriores permanece indeterminada.** No se ha demostrado un cambio de endpoint ni se atribuye el fallo a una región, a infraestructura o a una corrección posterior del motor. Los tres ERROR siguen visibles en los archivos de la campaña principal.

## Estado por proveedor: tres títulos en cada fila

Estos son los estados de la última observación disponible. Un OK acredita el contrato y las rutas exigidas para ese juego en su ejecución; la muestra no certifica todos los títulos del proveedor.

| Proveedor | OK | PARCIAL | ERROR | SIN_EJECUTOR | Resultado o trabajo restante |
| --- | ---: | ---: | ---: | ---: | --- |
| 1Spin4Win | 3 | 0 | 0 | 0 | Se acreditan los dominios pagados y la ejecución requerida en los tres títulos. |
| 3 Oaks | 0 | 0 | 3 | 0 | HTTP 403 al iniciar las demos desde el runner; no se registran giros. La causa externa no queda determinada. |
| Amusnet | 0 | 3 | 0 | 0 | HTTP 403 en `/gl/amusnet`; el adaptador conserva PARCIAL e inventario incompleto. El bloqueo observado es de arranque. |
| Belatra | 0 | 0 | 3 | 0 | Fallo TLS/SNI `TLSV1_UNRECOGNIZED_NAME`; no se acredita ejecución. |
| BGaming | 3 | 0 | 0 | 0 | Los tres títulos mantienen OK y sus comprobaciones pagadas y de cierre. |
| Blueprint Gaming | 0 | 0 | 0 | 3 | Sólo catálogo; falta un ejecutor registrado y verificado. |
| ELK Studios | 0 | 3 | 0 | 0 | Batch 2 resuelve identidad/endpoint y acredita dos rondas base por título. Faltan los cinco BMODES X01–X05 y el inventario completo de controles pagados. |
| Games Global | 0 | 3 | 0 | 0 | 12 Masks of Fire Drums queda en continuación/bonus sin binding. Los otros dos títulos no confirman el modo practice exigido. |
| Greentube / Novomatic | 0 | 0 | 0 | 3 | Sólo catálogo; falta un ejecutor registrado y verificado. |
| Hacksaw Gaming | 3 | 0 | 0 | 0 | Tres OK en la comprobación posterior con el mismo motor; los tres 404 principales permanecen documentados. |
| KA Gaming | 3 | 0 | 0 | 0 | Los tres títulos mantienen OK en la muestra comparable. |
| NetEnt | 0 | 0 | 0 | 3 | El registro activo sólo ofrece catálogo. El prototipo existente no está habilitado como ejecutor. |
| Nolimit City | 3 | 0 | 0 | 0 | Los tres títulos mantienen OK con sus modos y controles exigidos. |
| PG Soft | 0 | 0 | 0 | 3 | Sólo catálogo; falta un ejecutor registrado y verificado. |
| Play'n GO | 0 | 3 | 0 | 0 | Se observó launcher practice y configuración DEMO. Faltan perfil/cotización inicial vinculados, semántica de respuestas y cierre conciliado de estos títulos. |
| Playson | 0 | 3 | 0 | 0 | Falta contrato TEST observado con identidad, versión y cotización. La observación posterior encontró Turnstile y no obtuvo bootstrap del juego. |
| Playtech | 3 | 0 | 0 | 0 | 1 of a Kind y 15 Diamonds pasan a OK; 15 Stars Ablaze mantiene OK. |
| Pragmatic Play | 1 | 2 | 0 | 0 | Rat Royale mantiene OK. Chests acredita ambas compras y sus retornos, pero ante sigue desconocido. Sweet conserva desconocidos compras y ante. |
| Push Gaming | 0 | 3 | 0 | 0 | Continuaciones o elecciones de bonus sin binding; inventario pagado todavía incompleto. |
| Red Tiger | 0 | 0 | 3 | 0 | El showcase llega parcialmente, pero no entrega `platform/game/settings`; no se inicia un contrato verificable de juego. |
| Relax Gaming | 0 | 3 | 0 | 0 | Falta contrato observado del launcher/login demo. Try Game llegó a confirmación de edad; no se obtuvo inicialización. |
| RubyPlay | 0 | 3 | 0 | 0 | Ante permanece desconocido en los tres. En batch 2 Marlin acredita también su compra; queda el dominio pick observado sin resolver. |
| Wazdan | 0 | 0 | 0 | 3 | Sólo catálogo; falta un ejecutor registrado y verificado. |
| Yggdrasil | 0 | 3 | 0 | 0 | El diagnóstico final acredita seis muestras en Gladiators y la primera SPIN de Piggies con dos probes. Frenan variantes no reconocidas: Sword NORMAL→Wild, expandingWilds con `SetCounterCell` con `Multiplier=2` y BOMB/applyBombFeature en Foxx. |
| **Total** | **19** | **29** | **9** | **15** | **72 títulos; 57 resultados del motor y 15 títulos sin ejecutor.** |

Los nombres públicos, incluido **25 Cookies: Hit the Bonus™**, identifican los títulos; una redacción de captura no se interpreta como un cambio del nombre ni del estado del juego.

## Qué mejoró aunque un juego siga PARCIAL

### Compras e inventario pagado

Pragmatic Chests tiene dos muestras base y dos por cada una de sus dos compras, con terminal y retorno confirmados. Su variante de respuesta devuelve `purtr/puri` y omite `bl`; ahora se acredita mediante request, selector, eco de apuesta y precio, conservando los demás controles. El resultado sigue PARCIAL porque no se demuestra aún la ausencia o presencia completa de ante. Sweet no adquiere un inventario vacío por carecer de esos campos.

RubyPlay Marlin declara su compra desde el menú fresco `buy_feature_configs`, cotejado con el tipo y precio del cliente. Sus dos muestras base y sus dos compras de la campaña principal estaban cerradas y tenían retorno confirmado, pero `PURCHASE_DECLARATION` seguía pendiente porque faltaba publicar esa validación en los metadatos que consume el gate neutral. Batch 2 exige todas las muestras limpias y las pruebas de retorno antes de marcar el modo. Su nueva ejecución vuelve a cerrar dos bases y dos compras y **ya no presenta ese pendiente de compra**. Ahora se observó además pick, cuyo dominio sigue sin resolver, junto con ante desconocido. La variación entre muestras no se interpreta como creación o desaparición de una función del juego.

Harvest y Oasis declaran cero compras por la bandera explícita del servidor y siguen pendientes por ante. Declarar el menú, ejecutar una compra y demostrar todas sus ramificaciones son comprobaciones distintas; ninguna sustituye a las demás.

### Cierre y arranque portable

Los cambios Yggdrasil amplían familias concretas de resultados reconocidos. Un bonus cerrado no se cuenta como una ronda base ordinaria: se siguen exigiendo dos probes base reconocidos después. El diagnóstico histórico [40556151509](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40556151509) acreditó avances mayores en algunas rutas: Gladiators llegó al retorno de BB_DEATHMATCH_3 y Foxx acreditó dos bases y dos muestras de BUY_A_BONUS, GOLDEN_BET y GOLDEN_BET_WILD antes de un retorno desconocido en MAX_BUY_A_BONUS. Piggies se detuvo en el retorno del primer SPIN. Esos tres PARCIAL se conservan como evidencia anterior; esa corrida ya no es la fuente de las filas más recientes.

En la ejecución final [40561470969](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40561470969), commit `20a5f9f`, los tres vuelven a quedar PARCIAL con respuestas distintas. **Gladiators completa seis muestras**, dos de SPIN, dos de BB_DEATHMATCH_1 y dos de BB_DEATHMATCH_2, y se detiene ante Sword NORMAL→Wild en el primer probe de retorno de BB_DEATHMATCH_3. **Piggies confirma la primera SPIN con sus dos probes**, incluido un payline de 0,07 que antes no se reconocía; la segunda se detiene ante expandingWilds con `SetCounterCell` con `Multiplier=2`. **Foxx se detiene en el segundo probe de retorno de la primera SPIN**, ante BOMB/applyBombFeature; esa respuesta no contiene vidas y no alcanza a iniciar los modos pagados.

La comparación offline con el clasificador anterior también deja desconocidos los tres DTO que bloquean esta ejecución: **no se reproduce una regresión en esos casos**. Las diferencias de avance entre corridas corresponden a respuestas observadas distintas; no demuestran pérdida de las rutas acreditadas antes ni autorizan a sustituir el resultado más reciente por el histórico más favorable. Los contratos y límites concretos se detallan en [YGGDRASIL.md](YGGDRASIL.md).

ELK batch 2 enlaza el bootstrap oficial con la identidad/endpoint de cada demo. Arcanum, Ashoka y Ashoka Eternal cierran **dos rondas base por título**. Esto corrige el bloqueo de preparación de la campaña principal; no acredita los cinco BMODES X01–X05 pendientes ni el inventario universal de controles pagados. Los tres resultados permanecen PARCIAL.

Las observaciones públicas de [bootstrap 40551803690](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40551803690) y [Pragmatic 40552978574](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40552978574) documentan qué lanzadores/configuraciones se alcanzaron. No son pruebas de giro correcto. Los bloqueos de confirmación, Turnstile, identidad demo, cotización o semántica permanecen explícitos en [BOOTSTRAP.md](BOOTSTRAP.md).

La observación Pragmatic quedó incompleta: aportó cliente de Chests, recursos parciales de Rat y ningún cliente Sweet. La cadena `bls ausente → BetLevel nulo → request sin bl` es evidencia del parser observado, pero aún no certifica el inventario completo de controles activos. Se conserva UNKNOWN.

## Compilación, reproducibilidad y controles conservados

La [campaña principal 40553999461](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40553999461) terminó verde:

- **Python: 173 pruebas, cero fallos, cero errores y cero saltadas.**
- **Rust en Windows: tres pruebas unitarias y una de integración, las cuatro correctas.** La integración crea un proyecto/SQLite temporal e invoca el puente real sin jugar.
- Los jobs live registraron sus resultados. Que el job termine correctamente no significa que sus juegos sean OK.

Se versionaron fixtures y se identificaron claramente los añadidos sintéticos; no se presentan como capturas remotas ni se instalan para autorizar demos reales. Se conservaron los rechazos de cargo inconsistente, selector contradictorio, estado desconocido, muestreo insuficiente y retorno incompleto.

El [batch 2, Actions 40557863852](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40557863852), commit `5824816`, terminó también verde y confirmó **190 pruebas Python en Actions**, además de la comprobación local previa. Esa cifra corresponde al código posterior; se conserva separadamente la evidencia de las 173 pruebas del commit principal y de las cuatro pruebas Rust en Windows.

El [diagnóstico final Yggdrasil, Actions 40561470969](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40561470969), commit `20a5f9f`, terminó **SUCCESS y confirmó las 220 pruebas Python en CI**, además de la comprobación local previa. El job conserva los tres resultados PARCIAL del motor. Las cuatro pruebas Rust citadas arriba corresponden a la campaña principal `f5d9db2`, no a esta ejecución focal.

También se corrigió el exportador para que una propiedad JavaScript `cookie:` no eliminase el resto del bundle: las pruebas verifican simultáneamente conservación del código posterior y redacción de cookies, tokens, sesiones, contraseñas y secretos. No se publican bundles crudos ni credenciales.

## Procedencia de las comprobaciones posteriores

| Trabajo | Resultado incorporado | Fuente |
| --- | --- | --- |
| ELK y RubyPlay, batch 2 | Ambos jobs correctos; 190 pruebas Python verificadas en Actions. Tres PARCIAL por proveedor, con las mejoras y pendientes descritos arriba. | [Run 40557863852](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40557863852), commit `5824816`; [artefacto ELK](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40557863852/artifacts/12757713777) y [artefacto RubyPlay](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40557863852/artifacts/12758370971) |
| Diagnóstico histórico Yggdrasil | Tres PARCIAL; avances de rutas y retornos desconocidos conservados como evidencia anterior. Ya no es la fuente de las tres filas latest. | [Run 40556151509](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40556151509) |
| Diagnóstico final Yggdrasil, batch 3 | SUCCESS; 220 pruebas Python verificadas en Actions. Tres PARCIAL, con seis muestras completas en Gladiators, una SPIN completa en Piggies y un retorno desconocido por BOMB en Foxx. | [Run 40561470969](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40561470969), commit `20a5f9f`; [artefacto 12762445188](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40561470969/artifacts/12762445188) |

El primer intento de CI del batch 2 se interrumpió antes de jugar porque faltaba crear la carpeta `evidence` requerida por las pruebas. Se corrigió esa preparación y se verificó la ejecución posterior enlazada. Ese fallo previo no se contabiliza como un resultado de juego.

Los [CSV](latest-games.csv)/[JSON](latest-games.json) más recientes incorporan las nueve filas ELK/RubyPlay/Yggdrasil con su procedencia nueva; las tres Yggdrasil proceden ahora del run `40561470969`. Conservan los mismos 72 títulos, los 19 OK anteriores y el total **19/29/9/15**, con ocho nuevos OK sobre la referencia inicial y 70 muestras base completas. La campaña principal, la comprobación Hacksaw y el diagnóstico histórico Yggdrasil se conservan por separado para que las mejoras, los fallos observados y los bloqueos aún abiertos puedan revisarse sin confundir sus fuentes.
