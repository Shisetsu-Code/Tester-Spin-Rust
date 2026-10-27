"""Human-selected controls: one click, one HAR, no automatic exploration."""
import io,queue,threading
import tkinter as tk
from tkinter import ttk,messagebox
from PIL import Image,ImageTk
from tester_spin.hardfire_launcher import HardFireClient
from tester_spin.manual_controls import ManualControls
from tester_spin.responsive_ui import FlowFrame


class ManualControlsDialog(tk.Toplevel):
    def __init__(self,parent,data_root):
        super().__init__(parent);self.title("Opciones del juego · HardFire");self.geometry("850x720");self.minsize(650,500)
        self.data_root=data_root;self.session=ManualControls(HardFireClient());self.messages=queue.Queue();self.busy=False
        self.options={};self.point=None;self.original=None;self.image_box=None
        self.info=tk.StringVar(value="Abrí la demo en HardFire y seleccioná su pestaña.")
        ttk.Label(self,textvariable=self.info,wraplength=800).pack(fill="x",padx=10,pady=6)
        bar=FlowFrame(self,collapse_at=700,menu_label="Controles");bar.pack(fill="x",padx=10)
        self.common=tk.BooleanVar(value=False)
        ttk.Checkbutton(bar,text="Mostrar también controles habituales",variable=self.common).pack(side="left")
        self.refresh_btn=ttk.Button(bar,text="Actualizar opciones",command=self.refresh);self.refresh_btn.pack(side="left",padx=6)
        self.image_btn=ttk.Button(bar,text="Ver pantalla",command=self.show_image);self.image_btn.pack(side="left")
        self.save_btn=ttk.Button(bar,text="Guardar HAR pendiente",command=self.save_pending,state="disabled");self.save_btn.pack(side="left",padx=6)
        self.tree=ttk.Treeview(self,columns=("name","role"),show="headings",height=7,selectmode="browse")
        self.tree.heading("name",text="Opción visible");self.tree.heading("role",text="Tipo")
        self.tree.column("name",width=600);self.tree.column("role",width=110)
        self.tree.pack(fill="x",padx=10,pady=8);self.tree.bind("<<TreeviewSelect>>",self.select_ref)
        self.canvas=tk.Canvas(self,height=300,background="#202020",highlightthickness=0)
        self.canvas.pack(fill="both",expand=True,padx=10);self.canvas.bind("<Configure>",lambda _:self.render_image());self.canvas.bind("<Button-1>",self.select_point)
        self.hint=tk.StringVar(value="Elegí una opción. Si está dibujada dentro del juego, usá Ver pantalla y marcala en la imagen.")
        ttk.Label(self,textvariable=self.hint,wraplength=800).pack(fill="x",padx=10,pady=8)
        self.execute_btn=ttk.Button(self,text="Ejecutar y capturar",command=self.execute);self.execute_btn.pack(pady=(0,10))
        self.protocol("WM_DELETE_WINDOW",self.close);self.after(100,self.poll);self.refresh()

    def task(self,kind,operation):
        if self.busy:return
        self.busy=True
        for button in (self.refresh_btn,self.image_btn,self.execute_btn,self.save_btn):button.configure(state="disabled")
        def run():
            try:self.messages.put((kind,operation()))
            except Exception as exc:self.messages.put(("error",str(exc)))
        threading.Thread(target=run,daemon=True).start()

    def refresh(self):
        include=self.common.get()
        self.task("options",lambda:self.session.refresh(include_common=include))

    def show_image(self):self.task("image",self.session.image)

    def select_ref(self,_=None):
        if self.tree.selection():self.point=None;self.hint.set("Opción seleccionada: "+self.tree.item(self.tree.selection()[0],"values")[0])

    def select_point(self,event):
        if self.busy or not self.image_box:return
        x,y,w,h=self.image_box
        if not x<=event.x<x+w or not y<=event.y<y+h:return
        self.tree.selection_remove(*self.tree.selection());self.point=((event.x-x)/w,(event.y-y)/h)
        self.canvas.delete("choice");self.canvas.create_oval(event.x-7,event.y-7,event.x+7,event.y+7,outline="#ffba38",width=3,tags="choice")
        self.hint.set("Punto seleccionado en la imagen. Pulsá Ejecutar y capturar para enviar un único click.")

    def execute(self):
        selection=self.tree.selection();ref=self.options.get(selection[0]) if selection else None;point=self.point
        if ref is None and point is None:return
        def perform():
            result=self.session.execute(ref=ref,point=point)
            if result.get("har_path"):
                try:
                    from tester_spin.har_learning import isolate_capture
                    result["analysis"]=isolate_capture(result["har_path"],self.data_root)
                except Exception as exc:result["analysis_error"]=str(exc)
            return result
        self.task("executed",perform)

    def save_pending(self):
        def save():
            result=self.session.save_pending()
            if result.get("har_path"):
                try:
                    from tester_spin.har_learning import isolate_capture
                    result["analysis"]=isolate_capture(result["har_path"],self.data_root)
                except Exception as exc:result["analysis_error"]=str(exc)
            return result
        self.task("executed",save)

    def render_image(self):
        if self.original is None:return
        image=self.original.copy();image.thumbnail((max(1,self.canvas.winfo_width()),max(1,self.canvas.winfo_height())))
        self.photo=ImageTk.PhotoImage(image);w,h=image.size;x=(self.canvas.winfo_width()-w)//2;y=(self.canvas.winfo_height()-h)//2
        self.canvas.delete("all");self.canvas.create_image(x,y,image=self.photo,anchor="nw");self.image_box=(x,y,w,h);self.point=None

    def poll(self):
        if not self.winfo_exists():return
        try:
            kind,value=self.messages.get_nowait();self.busy=False
            for button in (self.refresh_btn,self.image_btn,self.execute_btn):button.configure(state="normal")
            self.save_btn.configure(state="normal" if self.session.pending else "disabled")
            if kind=="error":self.hint.set(value)
            elif kind=="options":
                self.options.clear();self.tree.delete(*self.tree.get_children());self.original=None;self.image_box=None;self.point=None;self.canvas.delete("all")
                self.info.set(str(value.get("title") or "Pestaña activa")+" · "+value["url"])
                for index,option in enumerate(value["options"]):
                    key=str(index);self.options[key]=option["ref"];self.tree.insert("", "end",iid=key,values=(option["name"],option["role"]))
                self.hint.set(("Hay controles dibujados: usá Ver pantalla para seleccionarlos. " if value.get("canvas") else "")+("Lista parcial; algunos controles no pudieron enumerarse." if value.get("truncated") else "Elegí una sola opción para ejecutarla y capturar su respuesta."))
            elif kind=="image":self.original=Image.open(io.BytesIO(value)).convert("RGB");self.render_image()
            elif kind=="executed":
                self.tree.delete(*self.tree.get_children());self.options.clear();self.original=None;self.image_box=None;self.point=None;self.canvas.delete("all")
                text=("Acción enviada. " if value["executed"] else "Acción no enviada: "+str(value.get("error"))+". ")+"HAR: "+str(value.get("har_path"))
                if value.get("capture_error"):text+=" · No se pudo guardar: "+value["capture_error"]+". Usá Guardar HAR pendiente; la acción ya fue consumida"
                if value.get("analysis"):
                    analysis=value["analysis"][0]
                    text+=" · Filtrado: "+analysis["output"]
                    diagnostic=analysis.get("capture_diagnostics",{})
                    details=diagnostic.get("issues",[])+diagnostic.get("contract_issues",[])+diagnostic.get("next_steps",[])
                    if details:text+=" · "+"; ".join(details)
                elif value.get("analysis_error"):text+=" · "+value["analysis_error"]
                self.hint.set(text+". Actualizá para ver el menú nuevo.")
        except queue.Empty:pass
        self.after(100,self.poll)

    def close(self):
        if self.busy:return
        if self.session.pending is not None:
            self.hint.set("Hay un HAR pendiente. Usá Guardar HAR pendiente antes de cerrar esta ventana.")
            return
        self.destroy()
