# Agregar un proveedor

Crear `tester_spin/providers/<proveedor>.py` con una clase que implemente `ProviderAdapter`.

Contrato mínimo:

```python
class NewProvider(ProviderAdapter):
    key = "new-provider"
    display_name = "New Provider"
    catalog_url = "https://..."

    def crawl_catalog(self, *, stop_event, progress, max_pages=100, on_game=None):
        # devolver list[Game]
        ...

    def test_game(self, game, *, spins, timeout_s, stop_event, progress):
        # descubrir todos los modos propios del proveedor y devolver GameTestResult
        ...
```

Luego registrar una instancia en `tester_spin/app.py`.

## Invariante de cobertura exhaustiva

### Declaración universal de opciones de pago

Todos los juegos de todos los proveedores deben emitir una declaración
`tester-spin/paid-options/v1`. Una declaración desconocida no equivale a cero.
`OK` exige inventario completo y validación de **cada** opción, sea ante bet,
compra de bonus, feature spin u otro modo especial de pago. Se mantienen además
los gates existentes de muestras, ramas y cierre de rondas.

Las primitivas de protocolo extraen dinámicamente las opciones de la sesión;
no se crean listas de compras por título. Cada primitiva tiene ID y versión.
Al encontrar una familia o binding desconocido se conserva la evidencia, se
amplía la primitiva con una prueba de regresión y se aplica la misma regla a
todos los juegos compatibles. Se reutiliza la interpretación, nunca el resultado
OK ni el inventario de un juego para otro.

`tester_spin.paid_options.write_paid_option_inventory` guarda
`paid-option-inventory.json`, vinculado a proveedor/juego/símbolo, con opciones,
tipos, costes declarados, cantidad (o `null` si es desconocida), primitiva y hashes
de evidencia de la ejecución. El gate universal exige evidencia coincidente y
una ejecución exitosa y terminal por ID. Una declaración de cero necesita la
misma evidencia de completitud que una declaración con opciones.

GPAS implementa el extractor en `playtech.primitives.paid_option_declaration`,
basado en el dominio de costes/configuración y sus bindings conocidos del
cliente. Los adaptadores todavía no conectados emiten explícitamente UNKNOWN
mediante el finalizador común y quedan PARCIAL; no se declara que esos proveedores
ya tengan interpretación completa. La campaña inicial se limitaba a ELK y
Playtech/GPAS; la auditoría aleatoria posterior amplió la muestra a los otros
proveedores con ejecución disponible.

`providers.paid_declarations` conecta los dominios explícitos de los demás
adaptadores al mismo contrato, con categorías requeridas por familia, bindings
entre selector y modo ejecutado, y referencias a la inicialización capturada.
No se completa una categoría ausente por deducción. Las opciones declaradas y
los conteos por categoría deben coincidir; los hashes se verifican al cerrar.
BGaming conserva su transporte `purchased_feature` para compras y ante bet,
manteniendo los roles de la declaración de inicialización. Red Tiger declara
ante/special desde sus catálogos explícitos gameModes y mathModes; ausencia de
esos campos sigue siendo desconocida.

La auditoría reproducible `evidence/campaign-20261026/universal-random.py`
eligió dos juegos por cada uno de los 12 proveedores con ejecución: 24 juegos.
Seis terminaron OK, doce PARCIAL y seis ERROR de conexión/inicialización.
Hay otros 12 proveedores con catálogo que todavía no tienen primitiva ejecutable.
La selección quedó guardada antes de ejecutar; no se descartaron resultados
desfavorables. Los dos casos BGaming se repitieron tras corregir su binding
común, preservando la primera ejecución. Los seis OK se contrastaron de nuevo
contra los conjuntos de opciones de sus capturas de configuración, sin llamar
al generador de declaraciones: coincidieron los seis conjuntos, incluido cero.
Esto verifica la muestra y no certifica todos los títulos del proveedor.

### Ejecutor Relax engine1 de demo

`relax.RelaxProvider` utiliza un contrato de bootstrap capturado por juego y
valida la autoridad de demo; no inventa lanzadores ni versiones. Una sesión FUN
nueva ejecuta `play` y `gamefinished`, comprobando terminales y saldo. Bonos,
decisiones, inventario completo y secuencias adicionales sin binding permanecen
PARCIAL. El contrato de Dream Drop Diamonds procede de una captura oficial;
otros juegos requieren evidencia propia compatible, sin tabla de excepciones.

### Ejecutor Push Hive REST de demo

`pushgaming.PushGamingProvider` obtiene el lanzador exacto desde la ficha oficial,
valida autoridad DEMO/FUN, autentica una sesión nueva y ejecuta `actions-v2` con
ACK por PUT. Soporta respuestas `data` y `state/steps` de juego base, incluidas
cascadas con premio acumulado y saldo reconciliado. No reintenta apuestas.
Compras, antebets y decisiones desconocidas quedan PARCIAL; no hay certificación
de inventario completo ni soporte universal de todos los juegos Push.

### Primitiva ELK de evidencia CAPI

`elk.ElkProvider` añade ejecución nativa DEF en demos oficiales de operador 44:
valida la identidad del lanzador, descubre versiones y endpoint, inicializa una
sesión nueva y captura purchase/checkwin. Reutiliza `convert_case` para verificar
coste, roundid y saldo con XML redactado. Los X-modes y controles de pago sin
cobertura permanecen PARCIAL; ecf3/ecf4 son las únicas familias reconocidas.

`elk_evidence.inspect_purchase_capture` verifica una captura real `purchase`
contra cotizaciones de init: autoridad e identidad del juego, modo, nivel,
coste, moneda, roundid y coherencia del XML público/saldos reportados.
Devuelve aceptación, nunca liquidación: faltan checkwin y cadena de balance.
No certifica inventario de controles ni genera peticiones.

`playngo_evidence.inspect_frame` reconoce exclusivamente el framing observado
en tres demos (opcode 2, longitud de un byte y etiquetas ProcessPacket/Commands).
Rechaza formatos desconocidos; no asigna semántica a campos, no serializa
acciones y no certifica cierre. Ambas primitivas conservan inventario incompleto.

`elk_evidence.convert_case` verifica capturas XML sin enviar solicitudes ni
modificar los originales. Extrae la unión de `betlevels/bmodes` del init real,
contrasta costes por nivel, request/respuesta de purchase, débito observado,
roundId de checkwin, premio, saldo final y continuidad de saldo entre rondas.
Un checkpoint enviado sin cierre, una liquidación ausente o datos contradictorios
quedan sin validar. También exige retorno DEF para certificar cobertura de los
modos del servidor y rechaza formatos o selectores de elección no reconocidos.

La cobertura de modos CAPI es un contrato distinto de la declaración completa
de controles de pago del cliente: el segundo permanece UNKNOWN y el resultado
PARCIAL hasta probar ese binding. El módulo no registra un ejecutor ELK ni
convierte automáticamente bmode en compra de bonus. Las capturas redactadas
no certifican continuidad de credenciales de sesión. La muestra de quince demos
produjo doce casos con todos los modos del servidor y 84 rondas verificadas;
los otros tres permanecen sin ese contrato completo.

`OK` significa que Tester-Spin recorrió todos los modos y todas las ramificaciones ejecutables que el contrato activo confirmó como requeridos durante la prueba. No alcanza con que una ruta representativa responda correctamente.

Reglas obligatorias para todos los adaptadores:

- ejecutar `SPIN` y cada modo requerido de apuesta/ante/purchase confirmado por el contrato activo;
- cuando una respuesta exponga alternativas seleccionables, probar **cada alternativa**;
- si seleccionar una alternativa consume la ronda, crear una ronda/sesión fresca para cada rama hermana en vez de reutilizar un `roundId` ya consumido;
- repetir la expansión recursivamente si una alternativa abre otro selector; el objetivo es recorrer hojas del árbol, no sólo el primer nivel;
- varios estados internos devueltos por una misma acción (`spinMode`, respins, free spins, cascadas, etc.) no son ramas por sí solos: sólo se expanden cuando el protocolo exige una elección/request diferente;
- una opción aleatoria (`Random`, cuando el proveedor la anuncia) se prueba como rama de protocolo, sin exigir un resultado semántico determinista;
- nunca inventar el wire contract de una rama. Si la rama existe pero su request todavía no está demostrado, conservar la evidencia y devolver `PARCIAL`;
- un límite defensivo de profundidad/cantidad de ramas puede detener una expansión patológica, pero alcanzar ese límite también deja la prueba `PARCIAL`;
- todo selector requerido y confirmado debe quedar representado en `discovered_modes` con `coverage_required=True`, `required_options` y `covered_options`, o mediante un contrato equivalente que el gate neutral pueda verificar.

El scheduler aplica `ProviderAdapter.finalize_test_result()` a **todos** los proveedores. Ese gate genera `path-coverage.json` y evita que un adaptador reporte `OK` si la metadata o los artefactos JSON muestran opciones descubiertas que no fueron recorridas. El gate es deliberadamente conservador: verifica cobertura, pero no fabrica requests específicos del proveedor.

Reglas generales del proyecto para todos los proveedores:

- una carpeta por juego bajo `data/providers/<provider_key>/<Nombre humano>/`;
- miniatura original/nativa guardada sin resize ni re-encode;
- `game.json` con URL pública, link directo al cliente cuando se conozca, ID interno del proveedor y metadata de protocolo reutilizable;
- respuestas de red originales guardadas en `.raw` antes o junto al parseo;
- modos del proveedor detectados dinámicamente cuando sea posible;
- estados todavía desconocidos se conservan como evidencia RAW, no se inventa una transición;
- GUI, scheduler y SQLite permanecen neutrales respecto del protocolo.
