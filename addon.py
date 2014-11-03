bl_info = {
    "name": "Export Freestyle edges to an .svg format",
    "author": "Folkert de Vries",
    "version": (1, 0),
    "blender": (2, 72, 1),
    "location": "properties > render > SVG Export",
    "description": "Adds the functionality of exporting Freestyle's stylized edges as an .svg file",
    "warning": "",
    "wiki_url": "",
    "category": "Render",
    }

import bpy
import parameter_editor
import os

import xml.etree.cElementTree as et 

from freestyle.types import StrokeShader, Interface0DIterator, Operators, BinaryPredicate1D
from freestyle.utils import get_dashed_pattern, getCurrentScene
from freestyle.shaders import RoundCapShader, SquareCapShader
from freestyle.functions import GetShapeF1D, CurveMaterialF0D
from freestyle.predicates import AndUP1D, ContourUP1D, SameShapeIdBP1D, NotUP1D, QuantitativeInvisibilityUP1D, TrueUP1D, pyZBP1D
from freestyle.chainingiterators import ChainPredicateIterator

from bpy.props import StringProperty, BoolProperty, EnumProperty, PointerProperty
from bpy.path import abspath

from itertools import repeat, dropwhile
from collections import OrderedDict

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

def render_height(scene) -> int:
    """Calculates the scene height in pixels"""
    return int(scene.render.resolution_y * scene.render.resolution_percentage / 100)

def create_path(filepath, scene) -> str:
    """Creates the output path for the svg file"""
    filepath = bpy.path.abspath(filepath)
    extension = "_{:04}.svg".format(scene.frame_current)
    # if a filename is given, add the frame number and safe
    if os.path.isfile(filepath):
        return filepath.split('.')[0] + extension
    # if a directory is given, use the blendfile's name as the filename
    elif os.path.isdir(filepath):
        filename = bpy.path.basename(bpy.context.blend_data.filepath)
        return filepath + "/" + filename + extension
    # else, try to create a file at the specified location and proceed.
    else:
        # errors in creating the file will be printed to the console
        open(filepath, 'a').close()
        return filepath.split('.')[0] + extension


class svg_export(bpy.types.PropertyGroup):
    """Implements the properties for the SVG exporter"""
    bl_idname = "RENDER_PT_svg_export"

    use_svg_export = BoolProperty(name="SVG Export", description="Export Freestyle edges to an .svg format")
    filepath = StringProperty(name="filepath", description="location to save the .svg file to", subtype='FILE_PATH',
                              default=bpy.context.user_preferences.filepaths.render_output_directory)

    
    split_at_invisible = BoolProperty(name="Split at Invisible", description="Split the stroke at an invisible vertex")
    object_fill = BoolProperty(name="Fill Contours", description="Fill the contour with the object's material color")

    _modes = [
        ('FRAME', "Frame", "Export a single frame", 0),
        ('ANIMATION', "Animation", "Export an animation", 1),
        ]

    mode = EnumProperty(items=_modes, name="Mode", default='FRAME')

    _linejoins = [
    ('MITTER', "Mitter", "Corners are sharp", 0),
    ('ROUND', "Round", "Corners are smoothed", 1),
    ('BEVEL', "Bevel", "Corners are bevelled", 2),
    ]

    linejoin = EnumProperty(items=_linejoins, name="Linejoin", default='ROUND')


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

        row = layout.row()
        row.prop(svg, "linejoin", expand=True)


def svg_export_header(scene):  
    svg = scene.svg_export
    render = scene.render

    if not (render.use_freestyle and scene.svg_export.use_svg_export):
        return

    width = int(render.resolution_x * render.resolution_percentage / 100)
    height = int(render.resolution_y * render.resolution_percentage / 100)
        
    # this may fail still. The error is printed to the console. 
    with open(create_path(svg.filepath, scene), "w") as f:
        f.write(svg_primitive.format(width, height))
        

def svg_export_animation(scene):
    """makes an animation of the exported SVG file """
    render = scene.render
    svg = scene.svg_export
    if render.use_freestyle and svg.use_svg_export and svg.mode == 'ANIMATION':
        write_animation(create_path(svg.filepath, scene), scene.frame_start, render.fps)


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

# - StrokeShaders - # 
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
        # extract style attributes from the linestyle and scene
        svg = getCurrentScene().svg_export
        style = {
            'fill': 'none',
            'stroke-width': linestyle.thickness,
            'stroke-linecap': linestyle.caps.lower(),
            'stroke-opacity': linestyle.alpha,
            'stroke': 'rgb({}, {}, {})'.format(*(int(c * 255) for c in linestyle.color)),
            'stroke-linejoin': svg.linejoin.lower(),
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
        print("SVG Export: writing to ", self.filepath)
        indent_xml(root)
        tree.write(self.filepath, encoding='UTF-16', xml_declaration=True)


class SVGFillShader(StrokeShader):
    """Creates SVG fills from the current stroke set"""
    def __init__(self, filepath, height, name):
        StrokeShader.__init__(self)
        # use an ordered dict to maintain input and z-order
        self.shape_map = OrderedDict()
        self.filepath = filepath
        self.h = height
        self._name = name

    def shade(self, stroke, func=GetShapeF1D(), curvemat=CurveMaterialF0D()):
        shape = func(stroke)[0].id.first
        item = self.shape_map.get(shape)
        if len(stroke) > 2:
            if item is not None:
                item[0].append(stroke)
            else:
                # the shape is not yet present, let's create it. 
                material = curvemat(Interface0DIterator(stroke))
                *color, alpha = material.diffuse
                self.shape_map[shape] = ([stroke], color, alpha)       
        # make the strokes of the second drawing invisible
        for v in stroke:
            v.attribute.visible = False

    @staticmethod
    def pathgen(vertices, path, height):
        yield path
        for point in vertices:
            x, y = point
            yield '{:.3f}, {:.3f} '.format(x, height - y)
        yield 'z" />' # closes the path; connects the current to the first point

    def write(self):
        """Write SVG data tree to file """
        # initialize SVG
        tree = et.parse(self.filepath)
        root = tree.getroot()
        name = self._name

        # create XML elements from the acquired data
        elems = []
        path = '<path fill-rule="evenodd" stroke="none" fill-opacity="{}" fill="rgb({}, {}, {})"  d=" M '
        for strokes, col, alpha in self.shape_map.values():
            p = path.format(alpha, *(int(255 * c) for c in col))
            for stroke in strokes:
                elems.append(et.XML("".join(self.pathgen((sv.point for sv in stroke), p, self.h))))

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

        # make <g> for fills
        frame_group = et.XML('<g />')
        frame_group.attrib = {'id': "layer_fills", 'inkscape:groupmode': 'fills', 'inkscape:label': 'fills'}
        # reverse the elements so they are correctly ordered in the image
        frame_group.extend(reversed(elems))
        lineset_group.insert(0, frame_group)

        # write SVG to file
        indent_xml(root)
        tree.write(self.filepath, encoding='UTF-16', xml_declaration=True)

# - Callbacks - #
def add_svg_export_shader(scene, shaders_list, lineset, capshaders={RoundCapShader, SquareCapShader}) -> (object, int):
    path = create_path(scene.svg_export.filepath, scene)
    height = render_height(scene)
    split = scene.svg_export.split_at_invisible
    # we want to insert before the first (most likely only) stroke cap shader. if none, insert at the end
    index = next((i for i, s in enumerate(shaders_list) if type(s) in capshaders), -1)
    return (SVGPathShader.from_lineset(lineset, path, height, split, scene.frame_current), index)


def add_svg_fill_shader(scene, shaders_list, lineset) -> None:
    # this is very ugly/hacky: need to find a better way to not execute/register a callback if undesired
    if not scene.svg_export.object_fill:
        return False

    # reset the stroke selection (but don't delete the already generated ones)
    Operators.reset(delete_strokes=False)
    # shape detection
    upred = AndUP1D(QuantitativeInvisibilityUP1D(0), ContourUP1D())
    Operators.select(upred)
    # chain when the same shape and visible
    bpred = SameShapeIdBP1D()
    Operators.bidirectional_chain(ChainPredicateIterator(upred, bpred), NotUP1D(QuantitativeInvisibilityUP1D(0)))
    # sort according to the distance from camera
    Operators.sort(pyZBP1D())
    # render and write fills
    path = create_path(scene.svg_export.filepath, scene)
    renderer = SVGFillShader(path, render_height(scene), lineset.name)
    Operators.create(TrueUP1D(), [renderer,])
    renderer.write()


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
    parameter_editor.callbacks_style_post.append(add_svg_export_shader)
    parameter_editor.callbacks_lineset_post.append(add_svg_fill_shader)
    parameter_editor.callbacks_lineset_post.append(write_svg_export_shader)


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
    parameter_editor.callbacks_style_post.remove(add_svg_export_shader)
    parameter_editor.callbacks_lineset_post.remove(add_svg_fill_shader)
    parameter_editor.callbacks_lineset_post.remove(write_svg_export_shader)


if __name__ == "__main__":
    register()
