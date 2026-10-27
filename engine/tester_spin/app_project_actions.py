"""Three desktop actions; all disk and Git work stays off the Tk thread."""
import queue
import threading
from tkinter import messagebox, ttk

from tester_spin.project_actions import clear_history, export_reports, publish


class ProjectActionsMixin:
    def _build_project_actions(self, parent, before):
        row = ttk.LabelFrame(parent, text='Programa e informes', padding=6)
        if isinstance(parent, ttk.Panedwindow):
            parent.insert(0, row, weight=0)
        else:
            row.pack(fill='x', pady=(6, 0), before=before)
        self.project_action_buttons = []
        for text, kind in [('Subir programa a GitHub', 'program'),
                           ('Borrar historial del proveedor', 'clear'),
                           ('Subir reportes a GitHub', 'reports')]:
            button = ttk.Button(row, text=text, command=lambda value=kind: self._project_action(value))
            button.pack(side='left', padx=(0, 8))
            self.project_action_buttons.append(button)

    def _set_busy(self, busy):
        super()._set_busy(busy)
        for button in getattr(self, 'project_action_buttons', []):
            button.configure(state='disabled' if busy else 'normal')

    def _project_action(self, kind):
        if self._worker and self._worker.is_alive():
            return
        provider = self._provider()
        if kind == 'clear':
            question = (f'¿Borrar el historial de {provider.display_name}?\n\n'
                'Se reinician resultados y pendientes de cobertura. El catálogo y los HAR manuales se conservan. '
                'Se guarda una copia local para recuperación. Los informes de lotes anteriores se archivan. '
                'Esto no borra el historial ya publicado en GitHub.')
        else:
            content = 'el código, las pruebas y la documentación' if kind == 'program' else 'el último reporte de cada juego, con claves de sesión filtradas'
            question = (f'¿Publicar {content}?\n\nSe creará un commit y se enviará a origin en la rama actual. '
                'También se enviarán los commits locales pendientes de esa rama. Se usará tu acceso Git configurado.')
        if not messagebox.askyesno('Tester-Spin', question):
            return
        completed = queue.Queue()
        self._set_busy(True)
        self.stop_btn.configure(state='disabled')
        self.progress.configure(mode='indeterminate');self.progress.start(15)
        self.status_var.set('Procesando... El avance aparece en el registro.')

        def progress(text):
            self._events.put(('log', text))

        def work():
            try:
                if kind == 'clear':
                    path = clear_history(self.root_dir, self.storage, provider.key, progress)
                    message = f'Historial limpio: {provider.display_name}.\nCopia local: {path}'
                else:
                    if kind == 'reports':
                        export_reports(self.root_dir, self.storage, progress)
                    branch = publish(self.root_dir, kind, progress)
                    message = f'Publicación completada en origin/{branch}.'
                completed.put((True, message))
            except Exception as exc:
                completed.put((False, str(exc)))

        def poll():
            try:
                ok, message = completed.get_nowait()
            except queue.Empty:
                self.after(100, poll)
                return
            self.progress.stop();self.progress.configure(mode='determinate', maximum=100, value=100 if ok else 0)
            self._set_busy(False)
            self.status_var.set('Operación completada' if ok else 'No se pudo completar la operación')
            self._append_log(message)
            if kind == 'clear' and ok:
                self._refresh_games()
            (messagebox.showinfo if ok else messagebox.showerror)('Tester-Spin', message)

        self._worker = threading.Thread(target=work, daemon=True, name='project-maintenance')
        self._worker.start()
        self.after(100, poll)
