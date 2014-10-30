bl_info = {
    "name": "Export Freestyle edges to an .svg format",
    "author": "Folkert de Vries",
    "version": (1, 0),
    "blender": (2, 72, 1),
    "location": "properties > render > SVG Export",
    "description": "Adds the functionality of exporting Freestyle's stylized edges as an .svg file",
    "warning": "",
    "wiki_url": "",
    "category": "Render"}

import bpy
import parameter_editor

import xml.etree.cElementTree as et 

from freestyle.types import StrokeShader, Interface0DIterator

from bpy.props import StringProperty, BoolProperty, EnumProperty, PointerProperty
from bpy.path import abspath

from itertools import repeat

# register namespaces
et.register_namespace("", "http://www.w3.org/2000/svg")
et.register_namespace("inkscape", "http://www.inkscape.org/namespaces/inkscape")
et.register_namespace("sodipodi", "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd")


# use utf-8 here to keep ElementTree happy, end result is utf-16
svg_primitive = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="{:d}" height="{:d}">
</svg>"""


# xml namespaces
namespaces = {
    "inkscape": "http://www.inkscape.org/namespaces/inkscape",
    "svg": "http://www.w3.org/2000/svg",
    }

class svg_export(bpy.types.PropertyGroup):
    """Implements the properties for the SVG exporter"""
    bl_idname = "RENDER_PT_svg_export"

    use_svg_export = BoolProperty(name="SVG Export", description="Export Freestyle edges to an .svg format")
    filepath = StringProperty(name="filepath", description="location to save the .svg file to", subtype='FILE_PATH')

    
    split_at_invisible = BoolProperty(name="Split at Invisible", description="Split the stroke at an invisible vertex")
    object_fill = BoolProperty(name="Fill Contours", description="Fill the contour with the object's material color")

    _modes = [
        ("FRAME", "Frame", "Export a single frame", 0),
        ("ANIMATION", "Animation", "Export an animation", 1),
        ]

    mode = EnumProperty(items=_modes, name="Mode", default="FRAME")


class SVGExporterPanel(bpy.types.Panel):
    """Creates a Panel in the render context of the properties editor"""
    bl_idname = "RENDER_PT_SVGExporterPanel"
    bl_space_type = 'PROPERTIES'
    bl_label = "Freestyle SVG Export"
    bl_region_type = 'WINDOW'
    bl_context = "render"

    def draw_header(self, context):
        self.layout.prop(context.scene.svg_export, "use_svg_export", text="")

    def draw(self, context):
        layout = self.layout

        scene = context.scene
        svg = scene.svg_export
        freestyle = scene.render.layers.active.freestyle_settings

        layout.active = svg.use_svg_export and freestyle.mode != 'SCRIPT'

        row = layout.row()
        row.prop(svg, "mode", expand=True)

        row = layout.row()
        row.prop(svg, "filepath", text="")

        row = layout.row()
        row.prop(svg, "split_at_invisible")
        row.prop(svg, "object_fill")


#
#   The error message operator. When invoked, pops up a dialog 
#   window with the given message.   
#
class SVGExportErrorOperator(bpy.types.Operator):
    bl_idname = "error.SVGExportError"
    bl_label = "SVGExportError"
    type = StringProperty()
    message = StringProperty()
 
    def execute(self, context):
        self.report({'INFO'}, self.message)
        print(self.message)
        return {'FINISHED'}
 
    def invoke(self, context, event):
        wm = context.window_manager
        return wm.invoke_popup(self, width=400, height=200)
 
    def draw(self, context):
        self.layout.label("A message has arrived")
        row = self.layout.split(0.25)
        row.prop(self, "type")
        row.prop(self, "message")
        row = self.layout.split(0.80)
        row.label("") 
        row.operator("error.ok")

def svg_export_header(scene):  
    svg = scene.svg_export
    render = scene.render

    if not (render.use_freestyle and scene.svg_export.use_svg_export):
        return

    width = int(render.resolution_x * render.resolution_percentage / 100)
    height = int(render.resolution_y * render.resolution_percentage / 100)

    
    path = abspath(svg.filepath) + "_{:04}.svg".format(scene.frame_current)
    
    #try:
    with open(path, "w") as f:
        f.write(svg_primitive.format(width, height))
    # except:
    #     # TODO investigate whether this error can be propagated to the UI
    #     # invalid path is properly handled in the parameter editor
    #     print("SVG export: invalid path")

def svg_export_animation(scene):
    """makes an animation of the exported SVG file """
    render = scene.render
    svg = scene.svg_export
    if render.use_freestyle and svg.use_svg_export and svg.mode == 'ANIMATION':
        path = abspath(svg.filepath) + "_{:04}.svg".format(scene.frame_current)
        write_animation(path, scene.frame_start, render.fps)

def write_animation(filepath, frame_begin, fps=25):
    """Adds animate tags to the specified file."""
    tree = et.parse(filepath)
    root = tree.getroot()

    linesets = tree.findall(".//svg:g[@inkscape:groupmode='lineset']", namespaces=namespaces)
    for i, lineset in enumerate(linesets):
        name = lineset.get('id')
        frames = lineset.findall(".//svg:g[@inkscape:groupmode='frame']", namespaces=namespaces)
        fills = lineset.findall(".//svg:g[@inkscape:groupmode='fills']", namespaces=namespaces)
        fills = reversed(fills) if fills else repeat(None, len(frames))

        n_of_frames = len(frames)
        keyTimes = ";".join(str(round(x / n_of_frames, 3)) for x in range(n_of_frames)) + ";1"

        style = {
            'attributeName': 'display',
            'values': "none;" * (n_of_frames - 1) + "inline;none",
            'repeatCount': 'indefinite',
            'keyTimes': keyTimes,
            'dur': str(n_of_frames / fps) + 's',
            }

        for j, (frame, fill) in enumerate(zip(frames, fills)):
            id = 'anim_{}_{:06n}'.format(name, j + frame_begin)
            # create animate tag
            frame_anim = et.XML('<animate id="{}" begin="{}s" />'.format(id, (j - n_of_frames) / fps))
            # add per-lineset style attributes
            frame_anim.attrib.update(style)
            # add to the current frame
            frame.append(frame_anim)
            # append the animation to the associated fill as well (if valid)
            if fill is not None:
                fill.append(frame_anim)

    # write SVG to file
    indent_xml(root)
    tree.write(filepath, encoding='UTF-16', xml_declaration=True)

# - SVG export - # 
class SVGPathShader(StrokeShader):
    """Stroke Shader for writing stroke data to a .svg file."""
    def __init__(self, name, style, filepath, res_y, split_at_invisible, frame_current):
        StrokeShader.__init__(self)
        # attribute 'name' of 'StrokeShader' objects is not writable, so _name is used
        self._name = name
        self.filepath = filepath
        self.h = res_y
        self.frame_current = frame_current
        self.elements = []
        self.split_at_invisible = split_at_invisible
        # put style attributes into a single svg path definition 
        self.path = '\n<path ' + "".join('{}="{}" '.format(k, v) for k, v in style.items()) + 'd=" M '

    @classmethod
    def from_lineset(cls, lineset, filepath, res_y, split_at_invisible, frame_current, *, name=""):
        """Builds a SVGPathShader using data from the given lineset"""
        name = name or lineset.name
        linestyle = lineset.linestyle
        # extract style attributes from the linestyle
        style = {
            'fill': 'none',
            'stroke-width': linestyle.thickness,
            'stroke-linecap': linestyle.caps.lower(),
            'stroke-opacity': linestyle.alpha,
            'stroke': 'rgb({}, {}, {})'.format(*(int(c * 255) for c in linestyle.color))
            }
        # get dashed line pattern (if specified)
        if linestyle.use_dashed_line:
            style['stroke-dasharray'] = ",".join(str(elem) for elem in get_dashed_pattern(linestyle))
        # return instance
        return cls(name, style, filepath, res_y, split_at_invisible, frame_current)

    @staticmethod
    def pathgen(stroke, path, height, split_at_invisible, f=lambda v: not v.attribute.visible):
        """Generator that creates SVG paths (as strings) from the current stroke """
        it = iter(stroke)
        # start first path
        yield path
        for v in it:
            x, y = v.point
            yield '{:.3f}, {:.3f} '.format(x, height - y)
            if split_at_invisible and v.attribute.visible == False:
                # end current and start new path; 
                yield '" />' + path
                # fast-forward till the next visible vertex
                it = dropwhile(f, it)
                # yield next visible vertex           
                svert = next(it, None)
                if svert is None:
                    break
                x, y = svert.point 
                yield '{:.3f}, {:.3f} '.format(x, height - y)
        # close current path
        yield '" />'

    def shade(self, stroke):
        stroke_to_paths = "".join(self.pathgen(stroke, self.path, self.h, self.split_at_invisible)).split("\n")
        # convert to actual XML, check to prevent empty paths
        self.elements.extend(et.XML(elem) for elem in stroke_to_paths if len(elem.strip()) > len(self.path))

    def write(self):
        """Write SVG data tree to file """
        print("writing")
        tree = et.parse(self.filepath)
        root = tree.getroot()
        name = self._name
        
        # make <g> for lineset as a whole (don't overwrite)
        lineset_group = tree.find(".//svg:g[@id='{}']".format(name), namespaces=namespaces)
        if lineset_group is None:
            lineset_group = et.XML('<g/>')
            lineset_group.attrib = {
                'id': name,
                'xmlns:inkscape': namespaces["inkscape"],
                'inkscape:groupmode': 'lineset',
                'inkscape:label': name,
                }
            root.insert(0, lineset_group)

        # make <g> for the current frame
        id = "{}_frame_{:06n}".format(name, self.frame_current)
        frame_group = et.XML("<g/>")
        frame_group.attrib = {'id': id, 'inkscape:groupmode': 'frame', 'inkscape:label': id}
        frame_group.extend(self.elements)
        lineset_group.append(frame_group)

        # write SVG to file
        indent_xml(root)
        tree.write(self.filepath, encoding='UTF-16', xml_declaration=True)


def add_svg_export_shader(scene, shaders_list, lineset):
    path = abspath(scene.svg_export.filepath) + "_{:04}.svg".format(scene.frame_current)
    height = int(scene.render.resolution_y * scene.render.resolution_percentage / 100)
    split = scene.svg_export.split_at_invisible
    return [SVGPathShader.from_lineset(lineset, path, height, split, scene.frame_current),]

def write_svg_export_shader(scene, shaders_list, lineset):
    for shader in shaders_list:
        try:
            shader.write()
        except AttributeError:
            pass


def indent_xml(elem, level=0, indentsize=4):
    """Prettifies XML code (used in SVG exporter) """
    i = "\n" + level * " " * indentsize
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + " " * indentsize
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
        for elem in elem:
            indent_xml(elem, level + 1)
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
    elif level and (not elem.tail or not elem.tail.strip()):
        elem.tail = i

def register():
    # register UI
    bpy.utils.register_class(SVGExporterPanel)
    # register properties
    bpy.utils.register_class(svg_export)
    bpy.types.Scene.svg_export = bpy.props.PointerProperty(type=svg_export)
    # add callbacks
    bpy.app.handlers.render_init.append(svg_export_header)
    bpy.app.handlers.render_post.append(svg_export_animation)
    # manipulate shaders list
    parameter_editor.callbacks_base_style_post.append(add_svg_export_shader)
    parameter_editor.callbacks_lineset_post.append(write_svg_export_shader)
    # Error
    bpy.utils.register_class(SVGExportErrorOperator)




def unregister():
    # unregister UI
    bpy.utils.unregister_class(SVGExporterPanel)
    # unregister properties
    bpy.utils.unregister_class(svg_export)
    del bpy.types.Scene.svg_export
    # remove callbacks
    bpy.app.handlers.render_init.remove(svg_export_header)
    bpy.app.handlers.render_post.remove(svg_export_animation)
    # manipulate shaders list
    parameter_editor.callbacks_base_style_post.remove(add_svg_export_shader)
    parameter_editor.callbacks_lineset_post.remove(write_svg_export_shader)
    # Error
    bpy.utils.unregister_class(SVGExportErrorOperator)



if __name__ == "__main__":

    register()
