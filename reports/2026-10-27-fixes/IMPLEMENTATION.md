# Correcciones posteriores a la auditoría inicial

La referencia inicial está en [el informe de la primera campaña](../2026-10-27-actions/README.md): 72 juegos, 11 OK, 37 PARCIAL, 9 ERROR y 15 SIN_EJECUTOR. Los siguientes cambios requieren una nueva campaña para medir su resultado live.

## Cambios y evidencia

| Área | Corrección | Límite conservado |
| --- | --- | --- |
| Reproducibilidad | Fixtures versionados; prueba Rust crea SQLite y configuración temporal e invoca el puente Python real; CI instala sus dependencias. | Los fixtures sintéticos están identificados y no certifican resultados live. |
| Hacksaw | Dos muestras válidas por ruta y por elección; planificación acotada de muestras faltantes. | Se detiene ante ledger inválido, cierre incierto o timeout; no reintenta la operación. |
| 1Spin4Win | Resuelve flags efectivos sólo con herencia, llamada al padre y asignaciones demostrables; reconoce el ante legado y calcula su coste desde init. | Una propiedad desconocida sigue desconocida; un ante que entra en bonus sin contrato contable queda PARCIAL. |
| Pragmatic | Acepta el recibo de compra sin `bl` sólo cuando request, apuesta, precio, identificador, cierre y retorno aportan la misma prueba. | Un `bl` contradictorio se rechaza; esta excepción no se aplica al ante. |
| RubyPlay | Publica el dominio de compra desde menú fresco del servidor y tipo/precio del cliente enlazado. | Ante y elecciones sin dominio exhaustivo permanecen desconocidos. |
| Playtech | Admite un coste de líneas único enlazado; traza el selector default compilado hasta `GLU.game.playMoney`. | No usa una tabla de títulos/UUID ni infiere el binding sólo por cardinalidad o precio. |
| Yggdrasil | Reconoce reemplazo wild explícito, retiro de multiplicador creado y bonus automático con salida y premio conciliados. | El bonus reconocido no cuenta como base: después exige dos rondas base ordinarias. |
| Amusnet / Play'n GO | Completa la ejecución acotada de paths Amusnet y decodifica longitudes varint del framing Play'n GO. | No certifica semántica ni dominios que todavía carecen de evidencia. |

La evidencia de protocolos procede de [Actions 40550335443](https://github.com/Shisetsu-Code/Tester-Spin-Rust/actions/runs/40550335443). Las observaciones de bootstrap se ejecutan separadamente en Actions y no alteran los estados históricos.

### 1Spin4Win: prueba del cliente y del dinero

Las tres fuentes públicas estáticas recuperadas se cotejaron contra los SHA-256 de la captura de Actions:

- CashnFruits40: `3c7e3781833c0c0c12276e1859def72978a97d10d6cc1dbf9c62d0b1d8e596f8`.
- GoldenJokerHalloween: `39db514e5f5fb7f0177bde79831557a7b392ad40cc8f9a38558f26f4b117b2c1`.
- LuckyLegionFortune: `5200388fd1f1ae9dedfa837da7c2de6cde7022402fe5914fa53d62141dbe64d3`.

CashnFruits40 declara `sideBet=1`, `sideBetPercent=.5`, `halfLines=true`, `allWays=false` y divisor 1. El cliente convierte el toggle a selector de protocolo y redondea el incremento del coste. El init capturado permite derivar apuesta base 20 y ante 30 en unidades menores. GoldenJokerHalloween y LuckyLegionFortune prueban ausencia de los dos dominios a partir de sus propiedades efectivas; no a partir de listas vacías de un parser.

Los tests negativos verifican herencia distinta, asignación condicional, orden incorrecto del constructor, cargos inconsistentes, retornos sin débito, premios inconsistentes y bonus sin contrato. Una revisión independiente reprodujo y cerró dos errores encontrados durante la implementación. Los dos probes base del ante deben conciliar cada transición de saldo.

## Validación antes de publicar

- Suite completa Python: **173 tests, todos pasan**.
- `git diff --check`: limpio.
- Pruebas focalizadas verifican los rechazos de protocolos desconocidos y el número exacto de envíos; no se saltan pruebas para obtener verde.
- Rust/Windows y resultados live: pendientes de la campaña posterior al cambio; se publicarán en el informe de comparación.

Los cinco proveedores que sólo tienen catálogo no adquieren un ejecutor mediante estos cambios. HTTP 403, TLS y desafíos del proveedor deben seguir distinguiéndose de errores corregibles del motor.
