"""Keep the desktop arrangement across restarts and shared-source updates."""
import json,re,tempfile
from pathlib import Path
import tkinter as tk

class LayoutPreferences:
    def __init__(self,app,path):
        self.app,self.path=app,Path(path)
        self.panes={name:getattr(app,name) for name in ('sections','workspace','middle','detail_panes')}
        self.pending=None;self.restoring=True;self.closed=False;self.normal_geometry=None
        try:
            value=json.loads(self.path.read_text(encoding='utf-8'))
            self.value=value if isinstance(value,dict) else {}
        except (OSError,ValueError):self.value={}
        # Set window dimensions before FlowFrame and the panes calculate sizes.
        geometry=self.value.get('normal_geometry',self.value.get('geometry'))
        if isinstance(geometry,str) and re.fullmatch(r'\d+x\d+(?:[+-]\d+[+-]\d+)?',geometry):
            try:self.app.geometry(geometry);self.normal_geometry=geometry
            except tk.TclError:pass
        if self.value.get('maximized') is True:
            try:self.app.state('zoomed')
            except tk.TclError:pass
        app.bind('<ButtonRelease-1>',self.schedule,add='+')
        app.bind('<Configure>',self.configured,add='+')
        app.bind('<Destroy>',self.destroyed,add='+')
        app.protocol('WM_DELETE_WINDOW',self.close)
        self.restore_job=app.after(250,self.restore)

    def configured(self,event):
        if event.widget is self.app:self.schedule()

    def schedule(self,event=None):
        if self.closed or self.restoring:return
        if self.pending is not None:
            try:self.app.after_cancel(self.pending)
            except tk.TclError:pass
        self.pending=self.app.after(350,self.save)

    def save(self):
        self.pending=None
        if self.closed or self.restoring:return
        temporary=None
        try:
            state=self.app.state()
            if state in ('iconic','withdrawn') or not self.app.winfo_ismapped():return
            geometry=self.app.geometry()
            if state=='normal':self.normal_geometry=geometry
            sizes={}
            for name,pane in self.panes.items():
                extent=pane.winfo_width() if str(pane.cget('orient'))=='horizontal' else pane.winfo_height()
                sizes[name]=[pane.sashpos(i)/max(1,extent) for i in range(len(pane.panes())-1)]
            value={'geometry':geometry,'normal_geometry':self.normal_geometry or geometry,
                'maximized':state=='zoomed','panes':sizes,
                'columns':{column:self.app.tree.column(column,'width') for column in ('#0',*self.app.tree['columns'])}}
            self.path.parent.mkdir(parents=True,exist_ok=True)
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',prefix='ui-layout-',suffix='.tmp',dir=self.path.parent,delete=False) as output:
                temporary=Path(output.name);json.dump(value,output,indent=2)
            temporary.replace(self.path);temporary=None
        except (OSError,tk.TclError):pass
        finally:
            if temporary is not None:
                try:temporary.unlink(missing_ok=True)
                except OSError:pass

    def restore(self):
        self.restore_job=None
        if self.closed:return
        self.app.update_idletasks()
        sections=self.panes['sections'];position=0
        for i,child in enumerate(sections.panes()[:-1]):
            position+=self.app.nametowidget(child).winfo_reqheight()
            sections.sashpos(i,position);position=sections.sashpos(i)+5
        detail=self.panes['detail_panes'];children=detail.panes()
        if len(children)==3:
            detail.sashpos(0,max(48,self.app.nametowidget(children[0]).winfo_reqheight()))
            detail.sashpos(1,max(80,detail.winfo_height()-self.app.nametowidget(children[2]).winfo_reqheight()-5))
        stored=self.value.get('panes',{})
        if not isinstance(stored,dict):stored={}
        # Parent panes first, then their children; restore columns at final size.
        for name,pane in self.panes.items():
            self.app.update_idletasks()
            extent=pane.winfo_width() if str(pane.cget('orient'))=='horizontal' else pane.winfo_height()
            fractions=stored.get(name,[])
            if not isinstance(fractions,list):continue
            for i,fraction in enumerate(fractions[:len(pane.panes())-1]):
                if type(fraction) in (int,float) and 0<=fraction<=1:pane.sashpos(i,int(extent*fraction))
        self.app.update_idletasks()
        columns=self.value.get('columns',{})
        if isinstance(columns,dict):
            for column,width in columns.items():
                if column in ('#0',*self.app.tree['columns']) and type(width) is int and 40<=width<=4000:
                    self.app.tree.column(column,width=width)
        self.restore_job=self.app.after(75,self.restored)

    def restored(self):
        self.restore_job=None;self.restoring=False

    def destroyed(self,event):
        if event.widget is self.app:self.cancel()

    def cancel(self):
        self.closed=True
        for job in (self.pending,self.restore_job):
            if job is not None:
                try:self.app.after_cancel(job)
                except tk.TclError:pass
        self.pending=self.restore_job=None

    def close(self):
        self.save();self.cancel();self.app.destroy()
