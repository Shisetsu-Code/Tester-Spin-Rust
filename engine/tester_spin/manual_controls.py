"""Read visible controls, execute one human selection, save its full HAR."""
import base64
from tester_spin.hardfire_launcher import HardFireError

# Exact labels only: Buy Free Spins must never be mistaken for Spin.
COMMON={"spin","girar","autoplay","auto play","turbo","sound","sonido","mute","fullscreen","pantalla completa","settings","ajustes","help","ayuda","+","-","−"}
ROLES={"button","link","menuitem","checkbox","radio","option"}


class ManualControls:
    def __init__(self,client):
        self.client=client;self.observation=None;self.image_observed=False;self.pending=None

    def refresh(self,include_common=False):
        state=self.client._rpc("hardfire_status",{})
        if not state.get("connected") or not isinstance(state.get("tab_id"),int):raise HardFireError("Abrí la demo en HardFire y seleccioná su pestaña.")
        args={"tab_id":state["tab_id"],"limit":100,"max_bytes":48000}
        snapshot=self.client._rpc("hardfire_snapshot",args)
        options=[]
        for e in snapshot.get("elements",[]):
            if not e.get("visible") or e.get("disabled") or e.get("role") not in ROLES or not e.get("ref"):continue
            name=str(e.get("name") or e.get("text") or "Sin texto").strip()
            if not include_common and name.casefold() in COMMON:continue
            options.append({"ref":e["ref"],"name":name,"role":e["role"]})
        self.observation={**state,"options":options,"canvas":bool(snapshot.get("canvas")),"truncated":bool(snapshot.get("truncated") or snapshot.get("next_cursor"))}
        self.image_observed=False
        return self.observation

    def image(self):
        if self.observation is None:raise ValueError("Actualizá las opciones primero")
        result=self.client._rpc("hardfire_screenshot",{"tab_id":self.observation["tab_id"],"quality":80},raw=True)
        for block in result.get("content",[]):
            if block.get("type")=="image":
                image=base64.b64decode(block["data"],validate=True);self.image_observed=True;return image
        raise HardFireError("No se recibió una imagen del juego")

    def execute(self,*,ref=None,point=None):
        if self.pending is not None:raise ValueError("Guardá el HAR pendiente antes de ejecutar otra opción")
        observation=self.observation
        if observation is None:raise ValueError("Actualizá las opciones primero")
        if (ref is None)==(point is None):raise ValueError("Elegí una sola opción")
        if ref is not None and ref not in {e["ref"] for e in observation["options"]}:raise ValueError("La opción no pertenece a la pantalla mostrada")
        if point is not None and (not self.image_observed or len(point)!=2 or not all(isinstance(v,(int,float)) and not isinstance(v,bool) and 0<=v<=1 for v in point)):
            raise ValueError("Seleccioná un punto en la imagen actual")
        state=self.client._rpc("hardfire_status",{})
        if state.get("tab_id")!=observation["tab_id"] or state.get("url")!=observation["url"]:raise ValueError("La pestaña cambió. Actualizá antes de ejecutar.")
        tab={"tab_id":observation["tab_id"]}
        if not state.get("recording"):self.client._rpc("hardfire_record_start",tab)
        self.observation=None;self.image_observed=False
        error=None;executed=False
        try:
            if ref is not None:self.client._rpc("hardfire_click_ref",{**tab,"ref":ref})
            else:self.client._rpc("hardfire_click_relative",{**tab,"rx":point[0],"ry":point[1]})
            executed=True
            self.client._rpc("hardfire_wait",{**tab,"ms":1500})
        except Exception as exc:error=str(exc)
        finally:
            self.pending={"executed":executed,"error":error,"tab_id":tab["tab_id"],"late_attach_possible":not state.get("recording")}
        return self.save_pending()

    def save_pending(self):
        if self.pending is None:raise ValueError("No hay captura pendiente")
        result=dict(self.pending)
        try:
            saved=self.client._rpc("hardfire_record_save",{"tab_id":result["tab_id"]},timeout=120)
            if not saved.get("path"):raise HardFireError("HardFire no devolvió el archivo HAR")
            result.update(har_path=saved["path"],capture=saved);self.pending=None
        except Exception as exc:result.update(har_path=None,capture_error=str(exc))
        return result
