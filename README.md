Freestyle SVG Exporter
======================

A Blender addon for exporting stylized lines created by the Freestyle render engine to an SVG format. 
This is the development version: More features, more bugs!

<p align="center"><img src ="https://rawgit.com/folkertdev/freestyle-svg-exporter/master/Examples/car.svg" /></p>
<a style"font-size:12pt;" align="right" href="http://www.blendswap.com/blends/view/76715">Model by Blendergoodies</a>

To use (for now):
- Overwrite the current addon file with the one in this repository. 
- Enable the addon via User Preferences > Addons > SVG
- The exported .svg file is written to the default output path (Properties > Render > Output)

The GUI for the exporter should now be visible in the render tab of the properties window. If you experience any problems with the exporter please let me know. 

Options
=======

Mode
   Choice between Frame and Animation. Frame will render a single frame, Animation will bundle all rendered frames into a single .svg file. 

Split at Invisible
   By default the exporter won't take invisible vertices into account. Some stroke modifiers, like Blueprint, mark vertices as invisible to achieve a certain effect. Enabling this option will make the paths split when encountering an invisible vertex, which leads to a better result. 

Fill Contours
   The contour of objects is filled with their material color. Note that this features is somewhat unstable - especially when animating - because freestyle doesn't always produce a nice contour. 

Stroke Cap Style
   Defines the style the stroke caps will have in the SVG output. 


Exportable Properties
=====================

Because the representation of Freestyle strokes and SVG path objects is fundamentally different, a one on one translation between Freestyle and SVG is not possible. The main shortcoming of SVG compared to Freestyle is that Freestyle defines style per-point, where SVG defines it per-path. This means that Freestyle can produce much more complicated results that are impossible to achieve in SVG. 

The properties that can be exported are:

* Base color
* Base alpha
* Base thickness
* Dashes

Animations
==========

The exporter supports the creation of SVG animations. When the Mode is set to Animation, all frames from a render - one when f12 is pressed, all when shift f12 is pressed - into a single file. Most modern browsers support the rendering of SVG animations. 


<p align="center"><img src ="https://rawgit.com/folkertdev/freestyle-svg-exporter/master/Examples/rotating cube.svg" /></p>


Exporting Fills 
===============

Fills are colored areas extracted from a Freestyle render result. Specifically, they are defined by a combination of the Contour and External Contour edge type, combined with some predicates. The fill result can be unexpected, when the SVG renderer cannot correctly draw the path that the exporter has generated. This problem is extra apparent in animations. 

<p align="center"><img src="https://rawgit.com/folkertdev/freestyle-svg-exporter/master/Examples/final.svg" />
</p>
<a style"font-size:12pt;" align="right" href="https://github.com/xuv">Model by Julien Deswaef</a>

Fills support holes and layering. When using layers, the exporter tries to render objects with the same material as the same patch. The exporting of fills and especially the order in which they are layered is by no means perfect. In most cases, these problems can be easily solved in Inkscape or a text editor.  
