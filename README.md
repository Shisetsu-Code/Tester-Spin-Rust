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

## Auditoría en GitHub Actions — 27/10/2026

Se evaluaron 72 selecciones de 24 proveedores: **11 OK, 37 PARCIAL, 9 ERROR y
15 SIN_EJECUTOR**. El motor produjo resultados para 57 juegos; los otros 15
pertenecen a los cinco proveedores que sólo tienen catálogo.

- [Informe completo y causas por familia](reports/2026-10-27-actions/README.md)
- [Lista de juegos en CSV](reports/2026-10-27-actions/games.csv)
- [Datos, modalidades y evidencia en JSON](reports/2026-10-27-actions/games.json)
- [Cómo repetir la auditoría](docs/testing/github-actions.md)

La auditoría usa el motor Python incluido y prueba la compilación Rust en
Windows. Los fallos originales de fixtures, contratos locales y la base SQLite
ausente se documentan en el informe; estos resultados no certifican todos los
juegos del catálogo ni implican que la suite completa esté pasando.

