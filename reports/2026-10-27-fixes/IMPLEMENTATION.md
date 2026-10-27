# Correcciones posteriores a la auditoría inicial

La referencia inicial está en [el informe de la primera campaña](../2026-10-27-actions/README.md): 72 juegos, 11 OK, 37 PARCIAL, 9 ERROR y 15 SIN_EJECUTOR. Los cambios se contrastaron en una nueva campaña completa y ejecuciones focalizadas. [El informe de resultados](README.md) distingue cada ejecución y conserva los fallos anteriores.

## Cambios y evidencia

| Área | Corrección | Límite conservado |
| --- | --- | --- |
| Reproducibilidad | Fixtures versionados; prueba Rust crea SQLite y configuración temporal e invoca el puente Python real; CI instala sus dependencias. | Los fixtures sintéticos están identificados y no certifican resultados live. |
| Hacksaw | Dos muestras válidas por ruta y por elección; planificación acotada de muestras faltantes. | Se detiene ante ledger inválido, cierre incierto o timeout; no reintenta la operación. |
| 1Spin4Win | Resuelve flags efectivos sólo con herencia, llamada al padre y asignaciones demostrables; reconoce el ante legado y calcula su coste desde init. | Una propiedad desconocida sigue desconocida; un ante que entra en bonus sin contrato contable queda PARCIAL. |
| Pragmatic | Acepta el recibo de compra sin `bl` sólo cuando request, apuesta, precio, identificador, cierre y retorno aportan la misma prueba. | Un `bl` contradictorio se rechaza; esta excepción no se aplica al ante. |
| RubyPlay | Publica el dominio de compra desde menú fresco del servidor y tipo/precio del cliente enlazado; propaga la validación del modo cuando todas sus muestras y retornos están demostrados. | Ante y elecciones sin dominio exhaustivo permanecen desconocidos. |
| Playtech | Admite un coste de líneas único enlazado; traza el selector default compilado hasta `GLU.game.playMoney`. | No usa una tabla de títulos/UUID ni infiere el binding sólo por cardinalidad o precio. |
| Yggdrasil | Reconoce reemplazos wild observados, el DTO base de premios por líneas y las vidas de wilds ligadas a cascadas; concilia sus recibos de cobro. También conserva el reconocimiento previo de multiplicadores y bonus automáticos. | El bonus reconocido no cuenta como base: después exige dos rondas base ordinarias. Las formas y transiciones desconocidas siguen bloqueando esa confirmación. |
| ELK | Resuelve la identidad demo desde ficha, canonical, título y código oficial actuales; el handler y loader observados eligen `href` sobre un `data-src` obsoleto. | Una preparación fallida bloquea metadata antigua y no despacha gameplay. Los modos pagados aún requieren ejecución y cobertura. |
| Amusnet / Play'n GO | Completa la ejecución acotada de paths Amusnet y decodifica longitudes varint del framing Play'n GO. | No certifica semántica ni dominios que todavía carecen de evidencia. |

La evidencia de protocolos procede de [Actions 40550335443](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40550335443). Las observaciones de bootstrap se ejecutan separadamente en Actions y no alteran los estados históricos.

### 1Spin4Win: prueba del cliente y del dinero

Las tres fuentes públicas estáticas recuperadas se cotejaron contra los SHA-256 de la captura de Actions:

- CashnFruits40: `3c7e3781833c0c0c12276e1859def72978a97d10d6cc1dbf9c62d0b1d8e596f8`.
- GoldenJokerHalloween: `39db514e5f5fb7f0177bde79831557a7b392ad40cc8f9a38558f26f4b117b2c1`.
- LuckyLegionFortune: `5200388fd1f1ae9dedfa837da7c2de6cde7022402fe5914fa53d62141dbe64d3`.

CashnFruits40 declara `sideBet=1`, `sideBetPercent=.5`, `halfLines=true`, `allWays=false` y divisor 1. El cliente convierte el toggle a selector de protocolo y redondea el incremento del coste. El init capturado permite derivar apuesta base 20 y ante 30 en unidades menores. GoldenJokerHalloween y LuckyLegionFortune prueban ausencia de los dos dominios a partir de sus propiedades efectivas; no a partir de listas vacías de un parser.

Los tests negativos verifican herencia distinta, asignación condicional, orden incorrecto del constructor, cargos inconsistentes, retornos sin débito, premios inconsistentes y bonus sin contrato. Una revisión independiente reprodujo y cerró dos errores encontrados durante la implementación. Los dos probes base del ante deben conciliar cada transición de saldo.

## Segundo conjunto de correcciones

En ELK, ocho pruebas de bootstrap verifican identidad, autoridades, modo demo, contradicciones, redirects y bloqueo de metadata obsoleta. El mismo handler se comprobó contra el asset público completo con SHA-256 `5de9bf031729ad6a0b3ddc4df06630486df0d57a1a52ce0c70a8111a92bda057`. La ejecución focal posterior resolvió los tres juegos y cerró dos rondas base por juego; quedaron pendientes `X01–X05` y el inventario pagado.

En RubyPlay, la compra de Marlin ya tenía dos muestras correctas y retornos confirmados, pero el modo no publicaba `validated`. La propagación nueva exige todas las muestras programadas, terminalidad, ausencia de warnings/errores, directorios de evidencia distintos dentro del run y prueba persistida de dos bases de retorno. Las pruebas negativas cubren muestra faltante, fallo extra, ledger inválido, ruta duplicada y retorno incompleto. En Actions desapareció `PURCHASE_DECLARATION` de los faltantes; ante y la elección `pick` observada siguieron pendientes.

El exportador de diagnóstico también conserva el código que sigue a una propiedad JavaScript `cookie:` sin dejar de ocultar credenciales. El workflow focal crea sus directorios temporales antes de la suite y conserva su log. Un primer intento falló antes de ejecutar juegos por ese orden de preparación; el intento corregido pasó la suite íntegra.

## Tercer conjunto: contratos Yggdrasil observados

La captura [40556151509](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40556151509) permitió aislar tres respuestas que el motor cerraba, pero no podía reconocer como retorno ordinario:

- **Reemplazo Mace:** se admite la etiqueta `maceFeature` únicamente con la misma geometría explícita ya demostrada para Spear. Cada posición debe conservar el símbolo original declarado y convertirse en Wild; las demás celdas no pueden cambiar sin explicación. Los flags de bonus y los acumulados siguen comprobándose.
- **BaseGame con premios por líneas:** un reconocedor separado valida el ciclo completo de acciones tipadas, el tablero rectangular, la correspondencia de líneas y celdas premiadas, la moneda y la normalización respecto de la apuesta BASIC actual. No se confunde con la otra familia `base_game` ni se acepta una acción desconocida.
- **Vidas de wilds:** se admiten los presupuestos observados de dos y tres vidas. La identidad y posición se conservan al desplazar símbolos, y el decremento sólo se acepta después de participar en una cascada premiada. El reconocimiento requiere además modo `BASE_GAME`, cascadas terminadas, comandos `BASIC`, geometría real y contabilidad coherente. El parser de acciones aislado rechaza estas vidas por defecto; no basta con quitar el campo nuevo.

Los tres contratos cotejan el cobro `C` con la ronda reconocida: cargo cero, identidad y avance, `wonamount`, `exactWon`, acumulados y premios de efectivo presentes. El runtime también compara cada `prize.gameId` presente con el identificador del juego que abrió la sesión; el contexto esperado procede de la petición y no del premio recibido. La revisión independiente encontró contradicciones que las comprobaciones anteriores dejaban pasar; se conservaron como regresiones negativas y se corrigieron. Los fixtures mantienen los subárboles reales con procedencia/hash e identificadores opacos redactados; las mutaciones negativas y el desplazamiento sintético adicional están identificados como pruebas construidas.

Los presupuestos superiores, los premios o estados incompatibles y las variantes de bonus no demostradas permanecen fuera del contrato. Dos probes base independientes siguen siendo necesarios para confirmar el retorno.

## Validación realizada

- Campaña completa [40553999461](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40553999461): **173 tests Python** y **4 tests Rust/Windows**, incluida la integración con el puente Python real, todos pasan.
- Conjunto final ELK/Ruby [40557863852](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40557863852): **190 tests Python**, todos pasan en ambos jobs; el mismo conjunto pasó localmente.
- Conjunto Yggdrasil [40561470969](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40561470969), commit `20a5f9f`: **220 tests Python** pasan en Actions y localmente; 463 archivos de código, pruebas y configuración coinciden con lo verificado. Los tres juegos permanecen PARCIAL por respuestas fuera de los contratos implementados; [el detalle Yggdrasil](YGGDRASIL.md) demuestra la mejora payline y describe los pendientes sin atribuirlos a una regresión.
- `git diff --check`: limpio.
- Pruebas focalizadas verifican los rechazos de protocolos desconocidos y el número exacto de envíos; no se saltan pruebas para obtener verde.
- Hacksaw: 32 muestras y 6 rondas de retorno cerradas en el follow-up con el mismo motor. Se observaron confirmaciones de premio; no hubo selectores de decisión en esos tres juegos. El soporte de muestreo de elecciones se verifica con las pruebas de transporte simulado identificadas como tales.

Los cinco proveedores que sólo tienen catálogo no adquieren un ejecutor mediante estos cambios. HTTP 403, TLS y desafíos del proveedor deben seguir distinguiéndose de errores corregibles del motor.
