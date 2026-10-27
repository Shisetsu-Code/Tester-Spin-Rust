"""Small wrapping containers for the desktop controls."""
from tkinter import ttk, Menu


def flow_positions(sizes, width, gap=8):
    width = max(1, int(width))
    boxes = []
    x = y = row_height = 0
    for requested_width, height in sizes:
        item_width = min(width, max(1, int(requested_width)))
        height = max(1, int(height))
        if x and x + item_width > width:
            y += row_height + gap
            x = row_height = 0
        boxes.append((x, y, item_width, height))
        x += item_width + gap
        row_height = max(row_height, height)
    return boxes, y + row_height if boxes else 0


class FlowFrame(ttk.Frame):
    def __init__(self, master, *, collapse_at=None, menu_label="Acciones", **kwargs):
        super().__init__(master, **kwargs)
        self.collapse_at = collapse_at
        self._menu_button = None
        if collapse_at:
            self._menu_button = ttk.Menubutton(self, text=menu_label)
            self._menu = Menu(self._menu_button, tearoff=False, postcommand=self._refresh_menu)
            self._menu_button.configure(menu=self._menu)
        self.pack_propagate(False)
        self.bind('<Configure>', self._schedule, add='+')
        self.bind('<Map>', self._schedule, add='+')
        self._pending = None
        self.after_idle(self.reflow)

    def _schedule(self, event=None):
        if self._pending is None:
            self._pending = self.after_idle(self.reflow)

    def reflow(self):
        self._pending = None
        width = self.winfo_width()
        if width < 2:
            return
        children = [c for c in self.winfo_children() if c is not self._menu_button]
        if self._menu_button is not None:
            if width < self.collapse_at:
                for child in children:
                    if child.winfo_manager() == 'pack':
                        child.pack_forget()
                    child.place_forget()
                self._refresh_menu()
                h = self._menu_button.winfo_reqheight()
                self._menu_button.place(x=0,y=0,width=min(width,self._menu_button.winfo_reqwidth()),height=h)
                if int(str(self.cget('height'))) != h:
                    self.configure(height=h)
                return
            self._menu_button.place_forget()
        for child in children:
            if getattr(child, '_flow_wrap', False):
                child.configure(wraplength=max(40, width-8))
        boxes, height = flow_positions([(c.winfo_reqwidth(), c.winfo_reqheight()) for c in children], width)
        # Entries marked expandable consume the remainder of their line.
        for index, child in enumerate(children):
            x,y,w,h = boxes[index]
            if getattr(child, '_flow_expand', False):
                remainder = width - max((bx+bw for bx,by,bw,bh in boxes if by == y), default=0)
                w += max(0,remainder)
                boxes[index] = (x,y,w,h)
                for next_index in range(index+1,len(boxes)):
                    bx,by,bw,bh = boxes[next_index]
                    if by == y:
                        boxes[next_index] = (bx+max(0,remainder),by,bw,bh)
            if child.winfo_manager() == 'pack':
                child.pack_forget()
            child.place(x=x,y=y,width=w,height=h)
        if int(str(self.cget('height'))) != max(1,height):
            self.configure(height=max(1,height))

    def _refresh_menu(self):
        self._menu.delete(0,'end')
        for child in self.winfo_children():
            if isinstance(child, ttk.Button):
                self._menu.add_command(label=child.cget('text'),command=child.invoke,
                                       state='disabled' if child.instate(['disabled']) else 'normal')
