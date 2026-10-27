# Tester Spin Rust: auditoría en GitHub Actions — 27/10/2026

**72 juegos de 24 proveedores: 11 OK, 37 PARCIAL, 9 ERROR y 15 SIN_EJECUTOR.**

El motor produjo 57 resultados: 31 juegos registraron al menos un intento y 26 se bloquearon antes de registrar intentos. Un intento registrado tampoco implica que el giro haya cerrado correctamente. Los 15 títulos de proveedores sin ejecutor se enumeran aparte y no se presentan como pruebas de juego realizadas.

## Fuentes y configuración

- [Corrida principal, 24 proveedores](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40544934511), commit `4c380ae6712e369795156e016dd187d2d639ef52`.
- [Validación RubyPlay tras corregir el muestreo de catálogo](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40545779063), commit `ecd68a6f251b93da69bfae3692d52d39fe0d788c`.
- Motor de producción sin cambios respecto de `bc7c0b5b83e56366bd802802598e6d760b380059`; se agregó infraestructura de prueba y reporte.
- Tres registros verificados por catálogo, sin selección aleatoria. La muestra no certifica el catálogo entero de ningún proveedor.
- `--spins 2` fija dos muestras por ruta en el scheduler; no significa sólo dos giros base. Request timeout 30 s y límite por juego 240 s.
- Estado canónico: payload final persistido en SQLite por el scheduler. No se usan aprobaciones manuales ni se promueven estados desde archivos intermedios.

La primera pasada RubyPlay no ejecutó juegos: el muestreador limitaba el catálogo a una página, mientras el adaptador REST valida todas las páginas antes de emitir registros. Se corrigió el muestreador; la segunda pasada verificó 223 entradas en tres páginas y ejecutó sus tres títulos seleccionados. Esta tabla usa esa segunda pasada y conserva ambos enlaces de procedencia.

## Resumen por proveedor

| Proveedor | OK | Parcial | Error | Sin ejecutor | Evidencia |
|---|---:|---:|---:|---:|---|
| Pragmatic Play | 1 | 2 | 0 | 0 | [Artefacto](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40544934511/artifacts/12752676544) |
| 1Spin4Win | 0 | 3 | 0 | 0 | [Artefacto](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40544934511/artifacts/12752437693) |
| Belatra | 0 | 0 | 3 | 0 | [Artefacto](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40544934511/artifacts/12752726551) |
| BGaming | 3 | 0 | 0 | 0 | [Artefacto](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40544934511/artifacts/12753195592) |
| KA Gaming | 3 | 0 | 0 | 0 | [Artefacto](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40544934511/artifacts/12752189061) |
| RubyPlay | 0 | 3 | 0 | 0 | [Artefacto](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40545779063/artifacts/12752916833) |
| Red Tiger | 0 | 0 | 3 | 0 | [Artefacto](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40544934511/artifacts/12752532281) |
| 3 Oaks | 0 | 0 | 3 | 0 | [Artefacto](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40544934511/artifacts/12752826117) |
| Yggdrasil | 0 | 3 | 0 | 0 | [Artefacto](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40544934511/artifacts/12751574498) |
| Hacksaw Gaming | 0 | 3 | 0 | 0 | [Artefacto](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40544934511/artifacts/12752761351) |
| Nolimit City | 3 | 0 | 0 | 0 | [Artefacto](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40544934511/artifacts/12752573046) |
| Playtech | 1 | 2 | 0 | 0 | [Artefacto](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40544934511/artifacts/12751938232) |
| Games Global | 0 | 3 | 0 | 0 | [Artefacto](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40544934511/artifacts/12752258274) |
| Amusnet | 0 | 3 | 0 | 0 | [Artefacto](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40544934511/artifacts/12751879958) |
| Play'n GO | 0 | 3 | 0 | 0 | [Artefacto](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40544934511/artifacts/12752388221) |
| Greentube / Novomatic | 0 | 0 | 0 | 3 | [Artefacto](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40544934511/artifacts/12752646942) |
| NetEnt | 0 | 0 | 0 | 3 | [Artefacto](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40544934511/artifacts/12752652053) |
| PG Soft | 0 | 0 | 0 | 3 | [Artefacto](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40544934511/artifacts/12752617783) |
| Blueprint Gaming | 0 | 0 | 0 | 3 | [Artefacto](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40544934511/artifacts/12752662667) |
| Relax Gaming | 0 | 3 | 0 | 0 | [Artefacto](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40544934511/artifacts/12752078331) |
| Playson | 0 | 3 | 0 | 0 | [Artefacto](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40544934511/artifacts/12753501124) |
| Wazdan | 0 | 0 | 0 | 3 | [Artefacto](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40544934511/artifacts/12752761892) |
| ELK Studios | 0 | 3 | 0 | 0 | [Artefacto](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40544934511/artifacts/12752856887) |
| Push Gaming | 0 | 3 | 0 | 0 | [Artefacto](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40544934511/artifacts/12753570556) |

## Juegos OK

| Proveedor | Juego | Modalidades con intentos validados |
|---|---|---:|
| Pragmatic Play | Rat Royale | 5 |
| BGaming | Black Friday Madness | 5 |
| BGaming | Joker Mask | 5 |
| BGaming | Luxury Feast Hold and Win | 3 |
| KA Gaming | 123 Vamos Capy | 1 |
| KA Gaming | 1960 Elvis Guayaba | 1 |
| KA Gaming | 1XBET La Pelota de la Rana Bloqueadas 2 Giros | 1 |
| Nolimit City | AFK Airport Security | 9 |
| Nolimit City | Apocalypse Super xNudge® | 8 |
| Nolimit City | Bangkok Hilton | 8 |
| Playtech | 15 Stars Ablaze™ | 12 |

## Qué falta y por qué

### Declaraciones de compras y ante

**1Spin4Win:** sus tres títulos hicieron dos giros base terminales. El adaptador no llena `feature_domains.purchase` ni `.ante`, de modo que el inventario universal queda UNKNOWN. Sus funciones actuales también devuelven listas vacías cuando no reconocen el cliente; por eso no corresponde convertir automáticamente una lista vacía en “cero opciones”. Falta una declaración por familia que distinga ausencia demostrada de configuración desconocida y conserve fuentes/init verificables.

**Pragmatic:** Sweet Bonanza POP carece de ambas declaraciones. Chests Of Cai Shen Infinity tiene compras declaradas y ejecutadas, pero no declara ante. Además, sus cuatro respuestas de compra incluyen `purtr`/`puri` y omiten `bl`; `pragmatic_declared_coverage.py` exige ese campo incondicionalmente. Los seis intentos de Chests tienen muestras suficientes, terminal y dos probes base confirmados. Falta reconocer esa variante de respuesta sin debilitar la vinculación request/response ni afirmar ausencia de ante sin evidencia.

**RubyPlay:** Go High Harvest y Mad Hit Oasis declaran cero compras pero no completan el dominio ante. Marlin Bonanza ejecutó base y compra dos veces, pero conserva dominios pagados incompletos y el dominio de elecciones `pick` sin resolver.

### Diferencia entre muestras ejecutadas y muestras exigidas

**Hacksaw:** Dr Zappo, Le Vampire y Wicked Grin ejecutaron todas las opciones descubiertas y tienen inventario/cobertura de opciones completos. El adaptador programa dos SPIN, pero una sola ejecución de cada compra o giro especial (`hacksaw/adapter.py`, construcción de `jobs`). El finalizador exige dos por ruta. Se debe alinear esa planificación con la política de muestras, o separar explícitamente muestras base y muestras de opciones. No se observó una compra rechazada en estos tres casos.

### Reconocimiento de cierre y rutas pendientes

**Yggdrasil:** los tres juegos se detuvieron por `UNRECOGNIZED_CLOSED_OUTCOME` durante un probe de retorno. La respuesta del probe consta como terminal y sin comandos pendientes, pero su resultado no se reconoce como estado base. El intento de nivel superior conserva terminal=false porque exige dos probes base reconocidos. Los inventarios de 4, 5 y 4 opciones están completos; quedan rutas sin ejecutar o acreditar después de la detención. Se necesitan fixtures de las respuestas rechazadas y del contrato de su familia para ampliar el clasificador, manteniendo las comprobaciones de cierre.

**Playtech:** 1 of a Kind y 15 Diamonds fallan con `UNBOUND_STAKE_MODE` y `BASE_MODE_UNBOUND`; falta enlazar sus modos de apuesta a los comandos GPAS. 15 Stars Ablaze sí terminó OK con sus variantes base y ante.

**Push Gaming / Games Global:** continúan incompletos los bindings de elecciones o continuaciones de bonus. Dos de los títulos Games Global tampoco confirman el modo de práctica requerido. Debe conservarse la detención cuando la continuación es desconocida, sin repetir una operación de estado incierto.

### Arranque desde una instalación limpia

Relax y Playson requieren contratos observados `analysis/observed-rest-contract.json`. Play’n GO necesita `analysis/observed-practice-base.json`. ELK no confirma la identidad/endpoint de las tres demos seleccionadas. Estos datos no están presentes en el checkout limpio y el bridge sólo copia otro conjunto de contratos. Sus resultados PARCIAL con cero intentos son bloqueos de preparación, no evidencia de giros completados. Los ejecutores recientes conservan además inventario pagado incompleto; aportar el contrato no garantiza automáticamente un OK.

### Acceso externo y ejecutores ausentes

Amusnet devuelve HTTP 403 en `/gl/amusnet` para sus tres títulos; el motor los etiqueta PARCIAL por su inventario incompleto, aunque el bloqueo observado es de arranque. 3 Oaks devuelve HTTP 403. Red Tiger obtiene parte del showcase, pero su launcher responde HTTP 403 y no entrega `platform/game/settings`. Belatra falla en TLS/SNI con `TLSV1_UNRECOGNIZED_NAME`. Son hechos observados desde el runner; esta corrida no determina si la causa externa es regional, de red o de configuración del proveedor.

Greentube, NetEnt, PG Soft, Blueprint y Wazdan sólo tienen catálogo en el registro activo: falta implementar y verificar sus ejecutores. Que exista un archivo prototipo NetEnt no implica que esté activado.


## Estado del código y de las pruebas

- Rust compila en Windows y pasa 3 pruebas unitarias. La prueba de integración falla al abrir `data/tester-spin.sqlite3`, ausente del checkout.
- La suite Python de la corrida principal ejecuta 108 pruebas y termina con 7 fallos y 13 errores reportados por unittest. Entre las causas están el conversor ELK no publicado, fixtures/capturas y contratos locales ausentes, y `execute_path` ausente en `amusnet_paths.py`.
- Las 17 pruebas enfocadas del muestreador y del reporte final pasan en la verificación local final. Comprueban estados no ejecutados, autoridad de SQLite, paginación, muestras y artefactos faltantes, preservación de parciales y normalización de contadores.
- Un job de auditoría exitoso significa que escribió resultados; no que todos sus juegos sean OK. Los fallos unitarios originales mantienen roja la corrida principal.

## Prioridad de trabajo

1. Alinear la política de muestras de Hacksaw y corregir los bindings de declaraciones Pragmatic/RubyPlay/1Spin4Win con pruebas por familia. No rebajar los controles para obtener OK.
2. Incorporar fixtures de los probes Yggdrasil y ampliar las familias de cierre; completar los dos bindings base de Playtech.
3. Hacer reproducible la instalación: fixtures de prueba, conversor ELK, función Amusnet pendiente, creación de SQLite y contratos de bootstrap portables.
4. Completar continuaciones e inventarios de los nuevos ejecutores; tratar 403/TLS como una línea de diagnóstico separada; implementar los cinco proveedores sólo de catálogo.

## Lista completa de los 72 títulos

| Proveedor | Juego | Estado | Cierres base acreditados | Causa |
|---|---|---|---:|---|
| Pragmatic Play | Chests Of Cai Shen – Infinity | PARCIAL | 2 | Ante sin declarar y verificador de compras exige bl en respuestas que lo omiten; las compras y retornos cerraron. |
| Pragmatic Play | Rat Royale | OK | 2 | Cobertura exigida por el motor verificada en esta corrida. |
| Pragmatic Play | Sweet Bonanza POP | PARCIAL | 2 | No se certificó el inventario de compras/ante; dos giros base cerraron. |
| 1Spin4Win | Cash'n Fruits 40 | PARCIAL | 2 | Faltan declaraciones completas de compras y ante; los dos giros base cerraron correctamente. |
| 1Spin4Win | Golden Joker Halloween | PARCIAL | 2 | Faltan declaraciones completas de compras y ante; los dos giros base cerraron correctamente. |
| 1Spin4Win | Lucky Legion Fortune | PARCIAL | 2 | Faltan declaraciones completas de compras y ante; los dos giros base cerraron correctamente. |
| Belatra | Coins Blast | ERROR | 0 | Fallo TLS/SNI TLSV1_UNRECOGNIZED_NAME contra demo.bltr-static.com. |
| Belatra | Penalty Blast | ERROR | 0 | Fallo TLS/SNI TLSV1_UNRECOGNIZED_NAME contra demo.bltr-static.com. |
| Belatra | Princess Suki | ERROR | 0 | Fallo TLS/SNI TLSV1_UNRECOGNIZED_NAME contra demo.bltr-static.com. |
| BGaming | Black Friday Madness | OK | 2 | Cobertura exigida por el motor verificada en esta corrida. |
| BGaming | Joker Mask | OK | 2 | Cobertura exigida por el motor verificada en esta corrida. |
| BGaming | Luxury Feast Hold and Win | OK | 2 | Cobertura exigida por el motor verificada en esta corrida. |
| KA Gaming | 123 Vamos Capy | OK | 2 | Cobertura exigida por el motor verificada en esta corrida. |
| KA Gaming | 1960 Elvis Guayaba | OK | 2 | Cobertura exigida por el motor verificada en esta corrida. |
| KA Gaming | 1XBET La Pelota de la Rana Bloqueadas 2 Giros | OK | 2 | Cobertura exigida por el motor verificada en esta corrida. |
| RubyPlay | Go High® Harvest | PARCIAL | 2 | Falta declarar presencia o ausencia de ante; dos giros base cerraron. |
| RubyPlay | Mad Hit® Marlin Bonanza | PARCIAL | 2 | Dominio de elecciones pick sin resolver e inventario pagado incompleto; base y compra cerraron. |
| RubyPlay | Mad Hit® Oasis | PARCIAL | 2 | Falta declarar presencia o ausencia de ante; dos giros base cerraron. |
| Red Tiger | Nightmare Family Megaways™ | ERROR | 0 | Launcher devuelve HTTP 403 y bootstrap no entrega platform/game/settings. |
| Red Tiger | Spooky Carnival | ERROR | 0 | Launcher devuelve HTTP 403 y bootstrap no entrega platform/game/settings. |
| Red Tiger | Year-Round Riches Clusterbuster™ | ERROR | 0 | Launcher devuelve HTTP 403 y bootstrap no entrega platform/game/settings. |
| 3 Oaks | 4 Hot Chillies | ERROR | 0 | HTTP 403 al iniciar la demo desde el runner; no se registraron giros. |
| 3 Oaks | Chili Coins XXXL | ERROR | 0 | HTTP 403 al iniciar la demo desde el runner; no se registraron giros. |
| 3 Oaks | Lucky Apple x2500 | ERROR | 0 | HTTP 403 al iniciar la demo desde el runner; no se registraron giros. |
| Yggdrasil | 3 Gladiators Vs Caesar | PARCIAL | 2 | La ronda de un probe termina, pero su resultado no se reconoce como base; no se confirma el retorno y se detienen rutas restantes. |
| Yggdrasil | 3 Piggies Of Bank | PARCIAL | 1 | La ronda de un probe termina, pero su resultado no se reconoce como base; no se confirma el retorno y se detienen rutas restantes. |
| Yggdrasil | 4 Foxx Crew Wildenergy Multimax | PARCIAL | 0 | La ronda de un probe termina, pero su resultado no se reconoce como base; no se confirma el retorno y se detienen rutas restantes. |
| Hacksaw Gaming | Dr Zappo | PARCIAL | 2 | Opciones especiales ejecutadas una vez; el scheduler exige dos muestras por ruta. |
| Hacksaw Gaming | Le Vampire | PARCIAL | 2 | Opciones especiales ejecutadas una vez; el scheduler exige dos muestras por ruta. |
| Hacksaw Gaming | Wicked Grin | PARCIAL | 2 | Opciones especiales ejecutadas una vez; el scheduler exige dos muestras por ruta. |
| Nolimit City | AFK Airport Security | OK | 4 | Cobertura exigida por el motor verificada en esta corrida. |
| Nolimit City | Apocalypse Super xNudge® | OK | 4 | Cobertura exigida por el motor verificada en esta corrida. |
| Nolimit City | Bangkok Hilton | OK | 6 | Cobertura exigida por el motor verificada en esta corrida. |
| Playtech | 1 of a Kind™ | PARCIAL | 0 | Modo de apuesta base sin binding (BASE_MODE_UNBOUND); inventario y acciones pendientes. |
| Playtech | 15 Diamonds™ | PARCIAL | 0 | Modo de apuesta base sin binding (BASE_MODE_UNBOUND); inventario y acciones pendientes. |
| Playtech | 15 Stars Ablaze™ | OK | 7 | Cobertura exigida por el motor verificada en esta corrida. |
| Games Global | 12 Masks of Fire Drums™ | PARCIAL | 0 | Continuación o elección de bonus sin binding; inventario pagado pendiente. |
| Games Global | 3 Lucky Rainbows Action Boost Max | PARCIAL | 0 | El adaptador no confirma el modo de práctica requerido; inventario pagado pendiente. |
| Games Global | 333 Boom Banks POWER COMBO | PARCIAL | 0 | El adaptador no confirma el modo de práctica requerido; inventario pagado pendiente. |
| Amusnet | 10 Bulky Fruits | PARCIAL | 0 | ValueError: HTTP 403 /gl/amusnet; inventario pagado pendiente. |
| Amusnet | 10 Burning Heart | PARCIAL | 0 | ValueError: HTTP 403 /gl/amusnet; inventario pagado pendiente. |
| Amusnet | 10 Glossy Hot | PARCIAL | 0 | ValueError: HTTP 403 /gl/amusnet; inventario pagado pendiente. |
| Play'n GO | *NSYNC Pop | PARCIAL | 0 | Falta perfil de práctica vinculado a una captura; no se registraron giros. |
| Play'n GO | 1001 Mystery Genie Fortunes | PARCIAL | 0 | Falta perfil de práctica vinculado a una captura; no se registraron giros. |
| Play'n GO | 13th Trial Hercules Abyssways | PARCIAL | 0 | Falta perfil de práctica vinculado a una captura; no se registraron giros. |
| Greentube / Novomatic | 1-2-3 Bingo!™ | SIN_EJECUTOR | 0 | El registro activo sólo ofrece catálogo; falta adaptador de ejecución. |
| Greentube / Novomatic | 100 Magnificent Crown | SIN_EJECUTOR | 0 | El registro activo sólo ofrece catálogo; falta adaptador de ejecución. |
| Greentube / Novomatic | 25 Red Hot 7 Clover Link™ | SIN_EJECUTOR | 0 | El registro activo sólo ofrece catálogo; falta adaptador de ejecución. |
| NetEnt | 101 Candies | SIN_EJECUTOR | 0 | El registro activo sólo ofrece catálogo; falta adaptador de ejecución. |
| NetEnt | Aftermath | SIN_EJECUTOR | 0 | El registro activo sólo ofrece catálogo; falta adaptador de ejecución. |
| NetEnt | Aloha! Christmas | SIN_EJECUTOR | 0 | El registro activo sólo ofrece catálogo; falta adaptador de ejecución. |
| PG Soft | Alchemy Gold | SIN_EJECUTOR | 0 | El registro activo sólo ofrece catálogo; falta adaptador de ejecución. |
| PG Soft | Alibaba's Cave of Fortune | SIN_EJECUTOR | 0 | El registro activo sólo ofrece catálogo; falta adaptador de ejecución. |
| PG Soft | Anubis Wrath | SIN_EJECUTOR | 0 | El registro activo sólo ofrece catálogo; falta adaptador de ejecución. |
| Blueprint Gaming | 3 Pots O' Riches Megaways Jackpot Royale Express | SIN_EJECUTOR | 0 | El registro activo sólo ofrece catálogo; falta adaptador de ejecución. |
| Blueprint Gaming | 3 Pots O' Riches Megaways Rapid Fire | SIN_EJECUTOR | 0 | El registro activo sólo ofrece catálogo; falta adaptador de ejecución. |
| Blueprint Gaming | 3 Skulls of Voodoo | SIN_EJECUTOR | 0 | El registro activo sólo ofrece catálogo; falta adaptador de ejecución. |
| Relax Gaming | AgroCulture | PARCIAL | 0 | Falta contrato observado de arranque de la demo; no se registraron giros. |
| Relax Gaming | Ancient Tumble | PARCIAL | 0 | Falta contrato observado de arranque de la demo; no se registraron giros. |
| Relax Gaming | Atlantis Crush | PARCIAL | 0 | Falta contrato observado de arranque de la demo; no se registraron giros. |
| Playson | 25 Cookies: Hit the Bonus™ | PARCIAL | 0 | Falta contrato REST observado para esta demo; inventario pagado pendiente. |
| Playson | 3 Chillies and Joker: Hold and Win | PARCIAL | 0 | Falta contrato REST observado para esta demo; inventario pagado pendiente. |
| Playson | 3 Luxor Pots: Hold and Win | PARCIAL | 0 | Falta contrato REST observado para esta demo; inventario pagado pendiente. |
| Wazdan | 12 Bells | SIN_EJECUTOR | 0 | El registro activo sólo ofrece catálogo; falta adaptador de ejecución. |
| Wazdan | 12 Coins | SIN_EJECUTOR | 0 | El registro activo sólo ofrece catálogo; falta adaptador de ejecución. |
| Wazdan | 12 Coins Grand Diamond Edition | SIN_EJECUTOR | 0 | El registro activo sólo ofrece catálogo; falta adaptador de ejecución. |
| ELK Studios | Arcanum | PARCIAL | 0 | Identidad y endpoint de la demo sin confirmar; inventario de modos pendiente. |
| ELK Studios | Ashoka | PARCIAL | 0 | Identidad y endpoint de la demo sin confirmar; inventario de modos pendiente. |
| ELK Studios | Ashoka Eternal | PARCIAL | 0 | Identidad y endpoint de la demo sin confirmar; inventario de modos pendiente. |
| Push Gaming | 10 Cash Bisons | PARCIAL | 0 | Continuación o elección de bonus sin binding; primer intento base sin cerrar e inventario incompleto. |
| Push Gaming | 10 Flaming Bisons | PARCIAL | 0 | Continuación o elección de bonus sin binding; primer intento base sin cerrar e inventario incompleto. |
| Push Gaming | 10 Pharaohs | PARCIAL | 0 | Continuación o elección de bonus sin binding; primer intento base sin cerrar e inventario incompleto. |

## Archivos y límites de interpretación

- [games.csv](games.csv): lista completa, estados, errores y contadores por modalidad.
- [games.json](games.json): datos estructurados, inventarios, ramas faltantes y procedencia por juego.
- [verification.json](verification.json): comprobaciones y fallos de la suite.

Los artefactos de Actions contienen índices y evidencias JSON saneadas, no una copia completa de cada HAR o respuesta cruda. Por ejemplo, permiten demostrar el gate de Yggdrasil que detuvo la prueba, pero no establecer el campo exacto de la respuesta que debe soportar una nueva primitiva. No se extrapolan porcentajes de éxito al catálogo completo. Las compras y giros inciertos no se repitieron para mejorar resultados.
