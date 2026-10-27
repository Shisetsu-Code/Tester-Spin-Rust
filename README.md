Tester Spin Rust — proyecto independiente

Abrir: doble clic en "Abrir Tester Spin.cmd".
Compilar: "Construir.cmd" (requiere Rust).

La interfaz es nativa Rust/egui. El motor Python se conserva como una copia
separada en engine/tester_spin y arranca sólo al pedir una operación.
config.json indica el intérprete Python ya instalado, los datos locales y la
carpeta original usada únicamente para leer miniaturas y copiar contratos.

data/tester-spin.sqlite3 es una copia consistente de la base original.
Las pruebas y los catálogos nuevos se guardan aquí. No se inicia aprendizaje
HAR, revisión global del historial, actualización Git ni escaneo periódico.
No se modifica el repositorio de Tester Spin ni su base original.

Uso:
- Buscar, filtrar por proveedor/estado y ordenar por los encabezados.
- Elegir un juego para consultar su último resultado; marcar varios para una tanda.
- Ctrl+C sobre la lista copia el enlace del juego activo y lo abre en Firefox.
- "Comprobar selección" valida el motor sin ejecutar juegos.
- "Probar selección" usa los adaptadores Python existentes y guarda resultados aquí.
- "Detener" solicita una detención conservando evidencias y operaciones pendientes.
- "Actualizar catálogo" agrega/actualiza juegos del proveedor seleccionado.
- "Actualizar vista" vuelve a leer esta copia local de SQLite.

La ejecución tiene las mismas capacidades y limitaciones de los adaptadores
originales. No se afirma que todas las compras estén implementadas en todos
los proveedores. Esta primera versión no migra los diálogos avanzados de
revisión/importación HAR, grupos de errores, VPN ni actualización automática.

Pruebas:
  cargo test
  <python de config.json> -m unittest discover -s tests
  target\release\tester-spin-rust.exe --check-data

Las mediciones y capturas de comprobación están en evidence/.

Publicación en GitHub: código fuente y pruebas. No incluye target/, data/, evidence/ ni artifacts/.
Para usarlo en otra PC, ajustar las rutas de config.json y aportar los datos y dependencias Python locales.

## Auditoría y correcciones en GitHub Actions — 27/10/2026

La última observación de los mismos 72 juegos de 24 proveedores contiene
**19 OK, 29 PARCIAL, 9 ERROR y 15 SIN_EJECUTOR**, frente a 11 OK y 37 PARCIAL
en la referencia inicial. Son ocho OK adicionales. Hay 57 resultados del motor;
los otros 15 títulos pertenecen a cinco proveedores que sólo ofrecen catálogo.

Este total combina la campaña principal con comprobaciones focalizadas en
sesiones nuevas; no es el resultado de una sola corrida. Cada juego conserva
su run, commit y artefacto de origen, y los resultados anteriores siguen
consultables. La muestra no certifica todo el catálogo de cada proveedor.

- [Informe de correcciones, resultados y pendientes](reports/2026-10-27-fixes/README.md)
- [Última observación de los 72 juegos en CSV](reports/2026-10-27-fixes/latest-games.csv)
- [Modalidades y evidencia por juego en JSON](reports/2026-10-27-fixes/latest-games.json)
- [Contratos Yggdrasil que todavía faltan](reports/2026-10-27-fixes/YGGDRASIL.md)
- [Referencia inicial e incidencias originales](reports/2026-10-27-actions/README.md)
- [Cómo repetir la auditoría y las pruebas](docs/testing/github-actions.md)

Los fixtures y la integración con SQLite ya son reproducibles en un checkout
limpio. La última ejecución focal confirmó **220 pruebas Python en Actions**;
la campaña principal confirmó **cuatro pruebas Rust en Windows**. Sus commits
y logs se detallan en el informe. Un job verde acredita la ejecución de la
auditoría; el estado OK/PARCIAL/ERROR se toma del resultado canónico de cada juego.
