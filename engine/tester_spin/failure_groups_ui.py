"""Explicit user selection of a diagnostic group; no automatic game actions."""
def show_groups(app):
    import tkinter as tk
    from tkinter import ttk, messagebox
    from .failure_groups import build_report, select_group, write_report
    provider=app._provider()
    rows=app.storage.latest_results(provider.key)
    report=build_report(rows)
    groups=report['groups']
    if not groups:
        messagebox.showinfo('Tester-Spin','No hay grupos pendientes para este proveedor.');return
    window=tk.Toplevel(app);window.title('Grupos de '+provider.display_name);window.geometry('900x560')
    choices=tk.Listbox(window,exportselection=False,height=10)
    choices.pack(fill='x',padx=10,pady=10)
    for group in groups:choices.insert('end',f"{group['affected']} juegos | {group['label']} | {group['code']} | {group['id']}")
    detail=tk.Text(window,wrap='word',height=16);detail.pack(fill='both',expand=True,padx=10)
    def selected():
        indexes=choices.curselection();return groups[indexes[0]] if indexes else None
    def refresh(event=None):
        group=selected()
        if group is None:return
        text='Representantes para analizar:\n\n'
        for game in group['representatives']:
            text+=game['name']+' ('+game['slug']+')\n'+game['error']+'\n'+game['run_dir']+'\n\n'
        text+='Afectados:\n'+', '.join(game['name'] for game in group['games'])
        detail.configure(state='normal');detail.delete('1.0','end');detail.insert('1.0',text);detail.configure(state='disabled')
    def retry():
        group=selected()
        if group is None:return
        slugs=select_group(report,group['id'],provider.key)
        games=[g for g in app.storage.list_games(provider.key) if g.slug in slugs]
        if not games:messagebox.showinfo('Tester-Spin','Los afectados ya no están en el catálogo.');return
        window.destroy();app._start_tests(games)
    def save():
        from datetime import datetime
        from uuid import uuid4
        stem=app.data_root/'reports'/('grupos-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:8])
        try:
            paths=write_report(rows,stem)
            messagebox.showinfo('Tester-Spin','Informe guardado:\n'+str(paths['markdown']))
        except OSError as exc:messagebox.showerror('Tester-Spin',str(exc))
    buttons=ttk.Frame(window);buttons.pack(fill='x',padx=10,pady=10)
    ttk.Button(buttons,text='REPROBAR GRUPO',command=retry).pack(side='left')
    ttk.Button(buttons,text='GUARDAR INFORME',command=save).pack(side='left',padx=10)
    choices.bind('<<ListboxSelect>>',refresh);choices.selection_set(0);refresh()
