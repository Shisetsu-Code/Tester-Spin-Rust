# Yggdrasil: validación real y contratos pendientes — 27/10/2026

**La comprobación final ejecutó los tres juegos y terminó con tres PARCIAL.** El workflow finalizó correctamente y pasó sus 220 pruebas Python; eso acredita el funcionamiento de la campaña y su suite, pero no convierte los resultados de juego en OK. Los tres bloqueos conservan un retorno a base sin confirmar porque una respuesta cerrada no corresponde todavía a un contrato semántico reconocido.

| Procedencia | Valor |
| --- | --- |
| Ejecución | [Actions 40561470969](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40561470969), conclusión `SUCCESS` |
| Código ejecutado | [`20a5f9f80ee987d45b4893a6d40b08152ef99671`](https://github.com/Shisetsu-Code/Tester-Spin-Rust/commit/20a5f9f80ee987d45b4893a6d40b08152ef99671) |
| Evidencia descargable | [Artefacto 12762445188](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40561470969/artifacts/12762445188), directorio `diagnostic-yggdrasil/` |
| Informe automático | `diagnostic-yggdrasil/audit.json` y evidencias de cada juego |
| Pruebas CI | **220/220 PASS** |
| Resultado de juego | **0 OK, 3 PARCIAL** |

Se solicitaron dos muestras por ruta. Cada retorno exige dos probes base independientes en la misma sesión. Una muestra solicitada sólo cuenta como completa cuando también acredita su retorno. Por ello, un intento puede mostrar `terminal=false` en el informe agregado aunque su ronda y su probe hayan recibido respuestas terminales: lo que no terminó de demostrarse es el contrato completo de la muestra y su retorno.

## Resultado y alcance de las tres observaciones

| Juego | Controles que sí se completaron en esta corrida | Punto que bloquea el retorno | Contrato pendiente |
| --- | --- | --- | --- |
| 3 Gladiators vs Caesar | Dos muestras SPIN, dos `BB_DEATHMATCH_1` y dos `BB_DEATHMATCH_2`, con sus **12 probes** de retorno confirmados | `BB_DEATHMATCH_3/sample-001`, primer probe | `swordFeature` con cuatro reemplazos explícitos de iconos `NORMAL` por `Wild` |
| 3 Piggies of Bank | Primera muestra SPIN con dos probes confirmados; uno de esos probes valida el nuevo contrato payline y su cobro | `SPIN/sample-002`, primer probe | Expansión de wild con multiplicador por celda: `SetCounterCell`, `SymbolsSet` y `expandingWilds` |
| 4 Foxx Crew WildEnergy MultiMax | La ronda SPIN y el primer probe de retorno se reconocen; el segundo probe se cobra y cierra, pero queda desconocido | `SPIN/sample-001`, segundo probe | Operación `applyBombFeature` enlazada al indicador `randomWinFeature="BOMB"` |

Las cinco compras declaradas de Piggies no llegaron a iniciarse. Foxx tampoco completó la primera muestra con su retorno. Esto no demuestra que sus compras fallen; esas rutas no se alcanzaron antes del bloqueo.

## 1. Gladiators: Sword con reemplazos NORMAL demostrados

Ruta dentro del artefacto:

`protocol/providers/yggdrasil/3-gladiators-vs-caesar/tests/20261027-184412-2b71d1/BB_DEATHMATCH_3/sample-001/return-to-base/probe-001`

El `return-to-base.json.json` de la muestra registra `REVIEW_REQUIRED`, cero bases consecutivas y un probe con `ok=true`, `terminal=true`, `known=false`, `base=false`, dos pasos y continuación `C`. Es la ronda opaca `round-20`; no se confunde con una ronda aún abierta.

Las entradas **28 y 29** del HAR contienen el giro base y su cobro. El DTO presenta `featuresUsed=["swordFeature"]` y cuatro entradas de `wildsAwarded` cuyos iconos originales tienen `iconType="NORMAL"`; esas mismas posiciones se convierten en `Wild`. El premio es **200 monedas × EUR 0,005 = EUR 1,00**. Los acumulados de monedas y dinero del giro, `cashWin`, `wonMoney`, el cobro `C`, `exactWon` y el premio `FIXED CASH EUR 1,00` concuerdan.

El contrato actual de reemplazos explícitos admite las formas demostradas para Spear y Mace. En una copia diagnóstica, sustituir únicamente la etiqueta Sword por Mace o Spear hace pasar la geometría, el ledger y el cobro existentes. El motor anterior `f5d9db2` también clasifica el DTO original como desconocido: no se atribuye este bloqueo a una regresión del cambio reciente.

**Trabajo mínimo pendiente:** incorporar esta forma de Sword conservando la comprobación del icono original, la correspondencia exacta de posiciones, los cambios de tablero explicados, las banderas de bonus y todo el dinero. No basta con permitir la etiqueta `swordFeature`: la captura anterior **40556151509, entrada 7**, ya usaba esa etiqueta con un icono de tipo `SCATTER`, fuera del contrato `NORMAL`. Ese caso requiere evidencia y semántica propias y no queda autorizado por el ejemplo nuevo.

## 2. Piggies: expansión de wild con multiplicador celular

Ruta del bloqueo dentro del artefacto:

`protocol/providers/yggdrasil/3-piggies-of-bank/tests/20261027-184614-1cfcee/SPIN/sample-002/return-to-base/probe-001`

La entrada **8** del HAR contiene un `BASE_SPIN` terminado directamente: `Finished`, `RESULTED`, un paso, apuesta **EUR 0,10**, premio y acumulados **0,00**, `isFinished=true`, sin comandos siguientes ni cobro `C`. El probe devuelve `ok=true`, `terminal=true`, `known=false`, `base=false` y `UNRECOGNIZED_CLOSED_OUTCOME`.

El tablero inicial ya contiene un `Wild` en **(0,0)** con counter celular `Multiplier=2`. La presentación añade, en orden:

1. `SetCounterCell` con `Multiplier=2` en (0,0).
2. `SetCounterCell` con `Multiplier=2` en (0,1).
3. `SymbolsSet`, animación `expandingWild`, que convierte (0,1) en `Wild`; su `ActionSource_Positions` identifica (0,0) como fuente.
4. `FeatureHappened("expandingWilds")`.
5. `PresentModeWin` y `accumulatedRoundWin` a cero.

El reconocedor de acciones equilibradas exige counters celulares vacíos y no modela `SetCounterCell` ni `expandingWilds`. El contrato payline recién añadido cubre la evaluación ganadora y su collect; no corresponde a este DTO sin premio. El replay exacto devuelve desconocido tanto con el clasificador actual como con `f5d9db2`.

### Prueba real de la mejora payline

La misma sesión sí demuestra que el arreglo anterior funciona con otra respuesta real:

| Entradas HAR, índices desde cero | Papel | Clasificador `f5d9db2` | Clasificador actual |
| --- | --- | --- | --- |
| 3 | SPIN, muestra 1, sin premio | Base reconocida | Base reconocida |
| 4 | Primer probe del retorno de muestra 1 | Base reconocida | Base reconocida |
| **5–6** | Segundo probe: paylines **EUR 0,07** y collect `C` | **Desconocido** | **Base reconocida y cobro conciliado** |
| 7 | SPIN, muestra 2, sin premio | Base reconocida | Base reconocida |
| 8 | Primer probe del retorno de muestra 2, expanding wild | Desconocido | Desconocido |

La primera muestra obtiene `CONFIRMED` con dos probes distintos, rondas 2 y 3. La segunda frena en la ronda 5. El informe acredita **una muestra SPIN completa con retorno**, sin ejecutar las compras posteriores.

**Trabajo mínimo pendiente:** un contrato que conserve el estado del tablero y vincule wild fuente, counter multiplicador, posición destino y sustitución explícita del símbolo, verificando orden, geometría y ledger. La terminalidad y la presentación de un premio cero no sustituyen esa comprobación.

## 3. Foxx: operación Bomb sin vidas de wild

Ruta del bloqueo dentro del artefacto:

`protocol/providers/yggdrasil/4-foxx-crew-wildenergy-multimax/tests/20261027-184651-f1518f/SPIN/sample-001/return-to-base/probe-002`

Las entradas **5 y 6** del HAR contienen el giro base y su cobro. El DTO tiene diez acciones y **no contiene vidas de wild**, por lo que el contrato nuevo de vidas no se activa. En `actions[2]` aparece `operateSymbols(operation="applyBombFeature")` para cuatro posiciones con símbolo `LOW_4`: **(4,0), (4,1), (5,0) y (5,1)**, sobre un tablero 6 × 6.

La envolvente declara dos estados de cascada: `respinNumber=0`, `gameMode="BASE_GAME"`, `lastRespin=false`, `randomWinFeature="BOMB"`; y `respinNumber=1`, `BASE_GAME`, `lastRespin=true`, `randomWinFeature=null`. El dinero es coherente: saldo inicial **10999,80**, apuesta **0,10**, saldo de compra **10999,70**, premio y acumulados **0,01**, cobro `wonamount/exactWon` **0,01** y saldo final **10999,71**, todos en EUR.

El primer probe del retorno se reconoce. El segundo ejecuta `BASIC + C` y cierra con `terminal=true`, pero conserva `known=false`, `base=false` y `UNRECOGNIZED_CLOSED_OUTCOME`. El replay del runtime y del parser de acciones del commit padre `2d5b3ee9f9738b4e85a71f33124b50545518f1e7` también devuelve desconocido para este DTO; no se ha demostrado una regresión por el contrato de vidas. Queda una sola base consecutiva y cero muestras completas con retorno para este juego.

**Trabajo mínimo pendiente:** modelar la operación `applyBombFeature`, su relación con las posiciones y símbolos del tablero y con el indicador `BOMB`, y la transición al estado final de la cascada. Deben conservarse las comprobaciones de apuesta, dinero, cobro e identidad. No procede convertir toda operación desconocida en una animación inocua ni ampliar el contrato de vidas a esta familia distinta.

## Integridad y localización de la evidencia

Los índices HAR de este documento empiezan en cero. Los hashes siguientes corresponden a los archivos **exportados y saneados**, no a un HAR original anterior al saneamiento.

| Juego | HAR dentro de `diagnostic-yggdrasil/` | SHA-256 del export |
| --- | --- | --- |
| Gladiators | `protocol/providers/yggdrasil/3-gladiators-vs-caesar/tests/20261027-184412-2b71d1/analysis/http.har.json` | `6f166ed008f0df58057ad26b93dc2884826c1f774e51f2a1a045fcc1ed4edc57` |
| Piggies | `protocol/providers/yggdrasil/3-piggies-of-bank/tests/20261027-184614-1cfcee/analysis/http.har.json` | `17034a61db1cb23893ca4ec8c77c1a468d227eb04aa0722288a7f474d4122bae` |
| Foxx | `protocol/providers/yggdrasil/4-foxx-crew-wildenergy-multimax/tests/20261027-184651-f1518f/analysis/http.har.json` | `207b46eadee3672e8ccc1c361778de140f2055d21eda14d4b88ac60c7d705db6` |

El texto de respuesta exportado de la entrada 8 de Piggies tiene SHA-256 `fe448b54ae57fd6d2a3a8f3fa7ba786594d73e5a8c390b5dc1fa4682abcad3f7`. Las pruebas diagnósticas se reprodujeron offline; este cierre documental no modifica producción ni ejecuta nuevas sesiones.

## Qué permite concluir la comparación

Los controles de dinero, identidad y dos probes independientes siguen vigentes. Los tres estados PARCIAL mantienen visibles los contratos que faltan y no certifican compras no ejecutadas. La mejora payline sí tiene un control positivo sobre el mismo DTO: antes quedaba desconocido y ahora se reconoce y concilia.

El avance observado depende también de las respuestas que entrega una sesión nueva. Un bloqueo más temprano en otra sesión no demuestra por sí solo una regresión. Tampoco se afirma que todas estas variantes aparecieran por primera vez: Sword ya estaba en capturas previas con otra semántica de icono. Las comparaciones de regresión aquí descritas usan el **mismo DTO capturado** contra los clasificadores anteriores y actuales.
