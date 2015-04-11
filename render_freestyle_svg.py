# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

# <pep8 compliant>

bl_info = {
    "name": "Freestyle SVG Exporter",
    "author": "Folkert de Vries",
    "version": (1, 0),
    "blender": (2, 72, 1),
    "location": "Properties > Render > Freestyle SVG Export",
    "description": "Exports Freestyle's stylized edges in SVG format",
    "warning": "",
    "wiki_url": "",
    "category": "Render",
    }

import bpy
import parameter_editor
import itertools
import os

import xml.etree.cElementTree as et

from freestyle.types import (
        StrokeShader,
        Interface0DIterator,
        Operators,
        Nature,
        BinaryPredicate1D,
        )
from freestyle.utils import (
    getCurrentScene,
    bounding_box,
    #inside_bounding_box,
    )
from freestyle.functions import GetShapeF1D, CurveMaterialF0D
from freestyle.predicates import (
        AndBP1D,
        AndUP1D,
        ContourUP1D,
        ExternalContourUP1D,
        NotUP1D,
        OrBP1D,
        OrUP1D,
        pyNatureUP1D,
        pyZBP1D,
        pyZDiscontinuityBP1D,
        QuantitativeInvisibilityUP1D,
        SameShapeIdBP1D,
        TrueBP1D,
        TrueUP1D,
        NotBP1D,

        )
from freestyle.chainingiterators import ChainPredicateIterator
from parameter_editor import get_dashed_pattern

from bpy.props import (
        BoolProperty,
        EnumProperty,
        PointerProperty,
        )
from bpy.app.handlers import persistent
from collections import OrderedDict
from functools import partial
from mathutils import Vector


# use utf-8 here to keep ElementTree happy, end result is utf-16
svg_primitive = """<?xml version="1.0" encoding="ascii" standalone="no"?>
<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="{:d}" height="{:d}">
</svg>"""


# xml namespaces
namespaces = {
    "inkscape": "http://www.inkscape.org/namespaces/inkscape",
    "svg": "http://www.w3.org/2000/svg",
    }

# wrap XMLElem.find, so the namespaces don't need to be given as an argument
def find_xml_elem(obj, search, namespaces, *, all=False):
    if all:
        return obj.findall(search, namespaces=namespaces)
    return obj.find(search, namespaces=namespaces)

find_svg_elem = partial(find_xml_elem, namespaces=namespaces)

# function that should soon be in freestyle.utils
# TODO: remove when it is
def inside_bounding_box(box_a, box_b):
    """
    Returns True if a in b, False otherewise
    """
    return (box_a[0].x >= box_b[0].x and box_a[0].y >= box_b[0].y and 
            box_a[1].x <= box_b[1].x and box_a[1].y <= box_b[1].y)


def render_height(scene):
    return int(scene.render.resolution_y * scene.render.resolution_percentage / 100)


def render_width(scene):
    return int(scene.render.resolution_x * scene.render.resolution_percentage / 100)


# stores the state of the render, used to differ between animation and single frame renders.
class RenderState:
    # Note that this flag is set to False only after the first frame
    # has been written to file.
    is_preview = True


@persistent
def render_init(scene):
    RenderState.is_preview = True


@persistent
def render_write(scene):
    RenderState.is_preview = False


def is_preview_render(scene):
    return RenderState.is_preview or scene.svg_export.mode == 'FRAME'


def create_path(scene):
    """Creates the output path for the svg file"""
    dirname = os.path.dirname(scene.render.frame_path())
    basename = bpy.path.basename(scene.render.filepath)
    if scene.svg_export.mode == 'FRAME':
        frame = "{:04d}".format(scene.frame_current)
    else:
        frame = "{:04d}-{:04d}".format(scene.frame_start, scene.frame_end)
    return os.path.join(dirname, basename + frame + ".svg")


class SVGExport(bpy.types.PropertyGroup):
    """Implements the properties for the SVG exporter"""
    bl_idname = "RENDER_PT_svg_export"

    use_svg_export = BoolProperty(
            name="SVG Export",
            description="Export Freestyle edges to an .svg format",
            )
    split_at_invisible = BoolProperty(
            name="Split at Invisible",
            description="Split the stroke at an invisible vertex",
            )
    object_fill = BoolProperty(
            name="Fill Contours",
            description="Fill the contour with the object's material color",
            )
    mode = EnumProperty(
            name="Mode",
            items=(
                ('FRAME', "Frame", "Export a single frame", 0),
                ('ANIMATION', "Animation", "Export an animation", 1),
                ),
            default='FRAME',
            )
    line_join_type = EnumProperty(
            name="Linejoin",
            items=(
                ('MITTER', "Mitter", "Corners are sharp", 0),
                ('ROUND', "Round", "Corners are smoothed", 1),
                ('BEVEL', "Bevel", "Corners are bevelled", 2),
                ),
            default='ROUND',
            )


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

        layout.active = (svg.use_svg_export and freestyle.mode != 'SCRIPT')

        row = layout.row()
        row.prop(svg, "mode", expand=True)

        row = layout.row()
        row.prop(svg, "split_at_invisible")
        row.prop(svg, "object_fill")

        row = layout.row()
        row.prop(svg, "line_join_type", expand=True)


@persistent
def svg_export_header(scene):
    if not (scene.render.use_freestyle and scene.svg_export.use_svg_export):
        return

    # write the header only for the first frame when animation is being rendered
    if not is_preview_render(scene) and scene.frame_current != scene.frame_start:
        return

    # this may fail still. The error is printed to the console.
    with open(create_path(scene), "w") as f:
        f.write(svg_primitive.format(render_width(scene), render_height(scene)))


@persistent
def svg_export_animation(scene):
    """makes an animation of the exported SVG file """
    render = scene.render
    svg = scene.svg_export

    if render.use_freestyle and svg.use_svg_export and not is_preview_render(scene):
        write_animation(create_path(scene), scene.frame_start, render.fps)


def write_animation(filepath, frame_begin, fps):
    """Adds animate tags to the specified file."""
    tree = et.parse(filepath)
    root = tree.getroot()

    linesets = find_svg_elem(tree, ".//svg:g[@inkscape:groupmode='lineset']", all=True)
    for i, lineset in enumerate(linesets):
        name = lineset.get('id')
        frames = find_svg_elem(lineset, ".//svg:g[@inkscape:groupmode='frame']", all=True)
        n_of_frames = len(frames)
        keyTimes = ";".join(str(round(x / n_of_frames, 3)) for x in range(n_of_frames)) + ";1"

        style = {
            'attributeName': 'display',
            'values': "none;" * (n_of_frames - 1) + "inline;none",
            'repeatCount': 'indefinite',
            'keyTimes': keyTimes,
            'dur': "{:.3f}s".format(n_of_frames / fps),
            }

        for j, frame in enumerate(frames):
            id = 'anim_{}_{:06n}'.format(name, j + frame_begin)
            # create animate tag
            frame_anim = et.XML('<animate id="{}" begin="{:.3f}s" />'.format(id, (j - n_of_frames) / fps))
            # add per-lineset style attributes
            frame_anim.attrib.update(style)
            # add to the current frame
            frame.append(frame_anim)

    # write SVG to file
    indent_xml(root)
    tree.write(filepath, encoding='ascii', xml_declaration=True)


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
            'stroke-linejoin': svg.line_join_type.lower(),
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
            if split_at_invisible and v.attribute.visible is False:
                # end current and start new path;
                yield '" />' + path
                # fast-forward till the next visible vertex
                it = itertools.dropwhile(f, it)
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
        scene = bpy.context.scene

        # create <g> for lineset as a whole (don't overwrite)
        # when rendering an animation, frames will be nested in here, otherwise a group of strokes and optionally fills.
        lineset_group = find_svg_elem(tree, ".//svg:g[@id='{}']".format(name))
        if lineset_group is None:
            lineset_group = et.XML('<g/>')
            lineset_group.attrib = {
                'id': name,
                'xmlns:inkscape': namespaces["inkscape"],
                'inkscape:groupmode': 'lineset',
                'inkscape:label': name,
                }
            root.append(lineset_group)

        # create <g> for the current frame
        id = "frame_{:04n}".format(self.frame_current)

        stroke_group = et.XML("<g/>")
        stroke_group.attrib = {'xmlns:inkscape': namespaces["inkscape"],
                               'inkscape:groupmode': 'layer',
                               'id': 'strokes',
                               'inkscape:label': 'strokes'}
        # nest the structure
        stroke_group.extend(self.elements)
        if scene.svg_export.mode == 'ANIMATION':
            frame_group = et.XML("<g/>")
            frame_group.attrib = {'id': id, 'inkscape:groupmode': 'frame', 'inkscape:label': id}
            frame_group.append(stroke_group)
            lineset_group.append(frame_group)
        else:
            lineset_group.append(stroke_group)

        # write SVG to file
        print("SVG Export: writing to", self.filepath)
        indent_xml(root)
        tree.write(self.filepath, encoding='ascii', xml_declaration=True)


class SVGFillBuilder:
    def __init__(self, filepath, height, name):
        self.filepath = filepath
        self._name = name
        self.stroke_to_fill = partial(self.stroke_to_svg, height=height)

    @staticmethod
    def pathgen(vertices, path, height):
        yield path
        for point in vertices:
            x, y = point
            yield '{:.3f}, {:.3f} '.format(x, height - y)
        yield 'z" />'  # closes the path; connects the current to the first point

    @staticmethod
    def get_merged_strokes(strokes):
        base_strokes = tuple(stroke for stroke in strokes if not is_poly_clockwise(stroke))
        # order is important; use OrderedDict
        merged_strokes = OrderedDict((s, list()) for s in base_strokes)

        for stroke in filter(is_poly_clockwise, strokes):
            for base in base_strokes:
                # don't merge when diffuse colors don't match
                if diffuse_from_stroke(stroke) != diffuse_from_stroke(stroke):
                    continue
                # only merge when the 'hole' is inside the base
                if stroke_inside_stroke(stroke, base):
                    merged_strokes[base].append(stroke)
                    break
            else:
                # if no merge is possible, add the stroke to the merged strokes
                merged_strokes.update({stroke:  []})
        return merged_strokes

    @staticmethod
    def stroke_to_svg(stroke, height):
        *color, alpha = diffuse_from_stroke(stroke)
        path = '<path fill-rule="evenodd" stroke="none" ' \
               'fill-opacity="{}" fill="rgb({}, {}, {})"  d=" M '.format(alpha, *(int(255 * c) for c in color))
        vertices = (svert.point for svert in stroke)
        return et.XML("".join(SVGFillBuilder.pathgen(vertices, path, height)))

    def create_fill_elements(self, strokes):
        merged_strokes = self.get_merged_strokes(strokes)
        elems = []
        for k, v in merged_strokes.items():
            # convert the base object to XML
            base = self.stroke_to_fill(k)
            # merge all d elements of child-strokes
            points = " ".join(self.stroke_to_fill(stroke).get('d') for stroke in v)
            # extend the base's vertices with the child's
            base.set('d', base.get('d') + points)
            elems.append(base)
        return elems

    def write(self, strokes):
        """Write SVG data tree to file """
        # initialize SVG
        tree = et.parse(self.filepath)
        root = tree.getroot()
        scene = bpy.context.scene
        lineset_group = find_svg_elem(tree, ".//svg:g[@id='{}']".format(self._name))
        fill_elements = self.create_fill_elements(strokes)

        if scene.svg_export.mode == 'ANIMATION':
            # add the fills to the <g> of the current frame
            frame_group = find_svg_elem(lineset_group, ".//svg:g[@id='frame_{:04n}']".format(scene.frame_current))
            if frame_group is None:
                # something has gone very wrong
                raise RuntimeError("SVGFillShader: frame_group is None")

        # <g> for the fills of the current frame
        fill_group = et.XML('<g/>')
        fill_group.attrib = {
            'xmlns:inkscape': namespaces["inkscape"],
            'inkscape:groupmode': 'layer',
            'inkscape:label': 'fills',
            'id': 'fills'
           }

        fill_group.extend(reversed(fill_elements))
        if scene.svg_export.mode == 'ANIMATION':
            frame_group.insert(0, fill_group)
        else:
            lineset_group.insert(0, fill_group)

        # write SVG to file
        indent_xml(root)
        tree.write(self.filepath, encoding='ascii', xml_declaration=True)

# utility stuff that should be moved to other files

def stroke_inside_stroke(a, b):
    box_a = bounding_box(a)
    box_b = bounding_box(b)
    return inside_bounding_box(box_a, box_b)

def get_strokes():
    return tuple(map(Operators().get_stroke_from_index, range(Operators().get_strokes_size())))


def is_poly_clockwise(stroke) -> bool:
    from freestyle.utils import pairwise 

    v = sum((v2.point.x - v1.point.x) * (v1.point.y + v2.point.y) for v1, v2 in pairwise(stroke))
    v1, *_, v2 = stroke 
    if (v1.point - v2.point).length > 1e-3:
        v += (v2.point.x - v1.point.x) * (v1.point.y + v2.point.y)
    return v > 0


class MaterialBP1D(BinaryPredicate1D):
    def __init__(self, *predicates):
        BinaryPredicate1D.__init__(self)

    def __call__(self, i1, i2):
        materials1 = {diffuse_from_fedge(fe).to_tuple() for fe in (i1.first_fedge, i1.last_fedge)}
        materials2 = {diffuse_from_fedge(fe).to_tuple() for fe in (i2.first_fedge, i2.last_fedge)}
        # not sure whether this can happen, but checking for it anyway
        if len(materials1) > 1 or len(materials2) > 1:
            return False 
        return materials1 == materials2 

def get_object_name(stroke):
    fedge = fedge_from_stroke(stroke)
    if fedge is None:
        return None 
    return fedge.viewedge.viewshape.name 

class StrokeCollector(StrokeShader):
    "Collects and Stores stroke objects"
    def __init__(self):
        StrokeShader.__init__(self)
        self.strokes = []

    def shade(self, stroke):
        self.strokes.append(stroke)

def diffuse_from_fedge(fe):
    if fe is None:
        return None
    if fe.is_smooth:
        return fe.material.diffuse
    else:
        right, left = fe.material_right, fe.material_left
        return (right if (right.priority > left.priority) else left).diffuse

# Binary Boolean operations still have some problems in the master version
class AndBP1D(BinaryPredicate1D):
    def __init__(self, *predicates):
        BinaryPredicate1D.__init__(self)
        self._predicates = predicates
        if len(predicates) < 1:
            raise ValueError("Expected two or more BinaryPredicate1D, got ", len(predicates))

    def __call__(self, i1, i2):
        return all(pred(i1, i2) for pred in self._predicates)


class OrBP1D(BinaryPredicate1D):
    def __init__(self, *predicates):
        BinaryPredicate1D.__init__(self)
        self._predicates = predicates
        if len(predicates) < 1:
            raise ValueError("Expected two or more BinaryPredicate1D, got ", len(predicates))

    def __call__(self, i1, i2):
        return any(pred(i1, i2) for pred in self._predicates)


class NotBP1D(BinaryPredicate1D):
    def __init__(self, predicate):
        BinaryPredicate1D.__init__(self)
        self._predicate = predicate

    def __call__(self, i1, i2):
        return (not self._predicate(i1, i2))

#

def diffuse_from_stroke(stroke, curvemat=CurveMaterialF0D()):
    material = curvemat(Interface0DIterator(stroke))
    return material.diffuse

# - Callbacks - #
class ParameterEditorCallback(object):
    """Object to store callbacks for the Parameter Editor in"""
    def lineset_pre(self, scene, layer, lineset):
        raise NotImplementedError()

    def modifier_post(self, scene, layer, lineset):
        raise NotImplementedError()

    def lineset_post(self, scene, layer, lineset):
        raise NotImplementedError()


class SVGPathShaderCallback(ParameterEditorCallback):
    @classmethod
    def modifier_post(cls, scene, layer, lineset):
        if not (scene.render.use_freestyle and scene.svg_export.use_svg_export):
            return []

        split = scene.svg_export.split_at_invisible
        cls.shader = SVGPathShader.from_lineset(
                lineset, create_path(scene),
                render_height(scene), split, scene.frame_current, name=layer.name + '_' + lineset.name)
        return [cls.shader]

    @classmethod
    def lineset_post(cls, scene, *args):
        if not (scene.render.use_freestyle and scene.svg_export.use_svg_export):
            return

        cls.shader.write()


class SVGFillShaderCallback(ParameterEditorCallback):
    @staticmethod
    def lineset_post(scene, layer, lineset):
        if not (scene.render.use_freestyle and scene.svg_export.use_svg_export and scene.svg_export.object_fill):
            return

        # reset the stroke selection (but don't delete the already generated strokes)
        Operators.reset(delete_strokes=False)
        # Unary Predicates: visible and correct edge nature
        BorderUP1D = lambda : pyNatureUP1D(Nature.BORDER)
        upred = AndUP1D(
            QuantitativeInvisibilityUP1D(0), 
            OrUP1D(ExternalContourUP1D(), BorderUP1D()),
            )
        # select the new edges
        Operators.select(upred)
        # Binary Predicates
        bpred = AndBP1D(
            MaterialBP1D(), 
            NotBP1D(pyZDiscontinuityBP1D()),
            )
        bpred = OrBP1D(bpred, AndBP1D(NotBP1D(bpred), AndBP1D(SameShapeIdBP1D(), MaterialBP1D())))
        # chain the edges
        Operators.bidirectional_chain(ChainPredicateIterator(upred, bpred))
        # export SVG
        collector = StrokeCollector()
        Operators.create(TrueUP1D(), [collector])
        # shader.write()
        builder = SVGFillBuilder(create_path(scene), render_height(scene), layer.name + '_' + lineset.name)
        builder.write(collector.strokes)
        # make strokes used for filling invisible
        for stroke in collector.strokes:
            for svert in stroke:
                svert.attribute.visible = False


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


classes = (
    SVGExporterPanel,
    SVGExport,
    )


def register():

    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.svg_export = PointerProperty(type=SVGExport)

    # add callbacks
    bpy.app.handlers.render_init.append(render_init)
    bpy.app.handlers.render_write.append(render_write)
    bpy.app.handlers.render_pre.append(svg_export_header)
    bpy.app.handlers.render_complete.append(svg_export_animation)

    # manipulate shaders list
    parameter_editor.callbacks_modifiers_post.append(SVGPathShaderCallback.modifier_post)
    parameter_editor.callbacks_lineset_post.append(SVGPathShaderCallback.lineset_post)
    parameter_editor.callbacks_lineset_post.append(SVGFillShaderCallback.lineset_post)

    # register namespaces
    et.register_namespace("", "http://www.w3.org/2000/svg")
    et.register_namespace("inkscape", "http://www.inkscape.org/namespaces/inkscape")
    et.register_namespace("sodipodi", "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd")


def unregister():

    for cls in classes:
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.svg_export

    # remove callbacks
    bpy.app.handlers.render_init.remove(render_init)
    bpy.app.handlers.render_write.remove(render_write)
    bpy.app.handlers.render_pre.remove(svg_export_header)
    bpy.app.handlers.render_complete.remove(svg_export_animation)

    # manipulate shaders list
    parameter_editor.callbacks_modifiers_post.remove(SVGPathShaderCallback.modifier_post)
    parameter_editor.callbacks_lineset_post.remove(SVGPathShaderCallback.lineset_post)
    parameter_editor.callbacks_lineset_post.remove(SVGFillShaderCallback.lineset_post)


if __name__ == "__main__":
    register()

