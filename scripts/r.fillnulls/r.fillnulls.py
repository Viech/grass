#!/usr/bin/env python
#
############################################################################
#
# MODULE:	r.fillnulls
# AUTHOR(S):	Markus Neteler
#               Updated to GRASS 5.7 by Michael Barton
#               Updated to GRASS 6.0 by Markus Neteler
#               Ring and zoom improvements by Hamish Bowman
#               Converted to Python by Glynn Clements
#               Add support to v.surf.bspline by Luca Delucchi
# PURPOSE:	fills NULL (no data areas) in raster maps
#               The script respects a user mask (MASK) if present.
#
# COPYRIGHT:	(C) 2001-2012 by the GRASS Development Team
#
#		This program is free software under the GNU General Public
#		License (>=v2). Read the file COPYING that comes with GRASS
#		for details.
#
#############################################################################


#%module
#% description: Fills no-data areas in raster maps using spline interpolation.
#% keywords: raster
#% keywords: elevation
#% keywords: interpolation
#%end
#%option G_OPT_R_INPUT
#%end
#%option G_OPT_R_OUTPUT
#%end
#%option
#% key: tension
#% type: double
#% description: Spline tension parameter
#% required : no
#% answer : 40.
#%end
#%option
#% key: smooth
#% type: double
#% description: Spline smoothing parameter
#% required : no
#% answer : 0.1
#%end
#%option
#% key: method
#% type: string
#% description: Interpolation method
#% required : yes
#% options : bilinear,bicubic,rst
#% answer : rst
#%end

import sys
import os
import atexit
import grass.script as grass

vecttmp = None
tmp1 = None
usermask = None
mapset = None

# what to do in case of user break:
def cleanup():
    #delete internal mask and any TMP files:
    if tmp1:
	rasts = [tmp1 + ext for ext in ['', '.buf', '_filled']]
	grass.run_command('g.remove', quiet = True, flags = 'f', rast = rasts)
    if vecttmp:
	grass.run_command('g.remove', quiet = True, flags = 'f', vect = vecttmp)
    grass.run_command('g.remove', quiet = True, rast = 'MASK')
    if usermask and mapset:
	if grass.find_file(usermask, mapset = mapset)['file']:
	    grass.run_command('g.rename', quiet = True, rast = (usermask, 'MASK'))

def main():
    global vecttmp, tmp1, usermask, mapset

    input = options['input']
    output = options['output']
    tension = options['tension']
    smooth = options['smooth']
    method = options['method']

    mapset = grass.gisenv()['MAPSET']
    unique = str(os.getpid())

    #check if input file exists
    if not grass.find_file(input)['file']:
	grass.fatal(_("<%s> does not exist.") % input)

    # check if a MASK is already present:
    usermask = "usermask_mask." + unique
    if grass.find_file('MASK', mapset = mapset)['file']:
	grass.message(_("A user raster mask (MASK) is present. Saving it..."))
	grass.run_command('g.rename', quiet = True, rast = ('MASK',usermask))

    #make a mask of NULL cells
    tmp1 = "r_fillnulls_" + unique

    #check if method is rst to use v.surf.rst
    if method == 'rst':
	# idea: filter all NULLS and grow that area(s) by 3 pixel, then
	# interpolate from these surrounding 3 pixel edge

	grass.message(_("Locating and isolating NULL areas..."))
	#creating 0/1 map:
	grass.mapcalc("$tmp1 = if(isnull($input),1,null())",
		      tmp1 = tmp1, input = input)

	#generate a ring:
	# the buffer is set to three times the map resolution so you get nominally
	# three points around the edge. This way you interpolate into the hole with 
	# a trained slope & curvature at the edges, otherwise you just get a flat plane.
	# With just a single row of cells around the hole you often get gaps
	# around the edges when distance > mean (.5 of the time? diagonals? worse 
	# when ewres!=nsres).
	# r.buffer broken in trunk for latlon, disabled

	#reg = grass.region()
	#res = (float(reg['nsres']) + float(reg['ewres'])) * 3 / 2

	#if grass.run_command('r.buffer', input = tmp1, distances = res, out = tmp1 + '.buf') != 0:

	# much easier way: use r.grow with radius=3.01
	if grass.run_command('r.grow', input = tmp1, radius = 3.01,
	                     old = 1, new = 2, out = tmp1 + '.buf') != 0:
	    grass.fatal(_("abandoned. Removing temporary map, restoring user mask if needed:"))

	grass.mapcalc("MASK = if($tmp1.buf == 2, 1, null())", tmp1 = tmp1)

	# now we only see the outlines of the NULL areas if looking at INPUT.
	# Use this outline (raster border) for interpolating the fill data:
	vecttmp = "vecttmp_fillnulls_" + unique
	grass.message(_("Creating interpolation points..."))
	## use the -b flag to avoid topology building on big jobs?
	## no, can't, 'g.region vect=' currently wants to see level 2
	if grass.run_command('r.to.vect', input = input, output = vecttmp,
			    type = 'point', flags = 'z'):
	    grass.fatal(_("abandoned. Removing temporary maps, restoring user mask if needed:"))

	# count number of points to control segmax parameter for interpolation:
	pointsnumber = grass.vector_info_topo(map = vecttmp)['points']

	grass.message(_("Interpolating %d points") % pointsnumber)

	if pointsnumber < 2:
	    grass.fatal(_("Not sufficient points to interpolate. Maybe no hole(s) to fill in the current map region?"))

	# remove internal MASK first -- WHY???? MN 10/2005
	grass.run_command('g.remove', quiet = True, rast = 'MASK')

	# print message is a usermask it was present
	if grass.find_file(usermask, mapset = mapset)['file']:
	    grass.message(_("Using user mask while interpolating"))
	    maskmap = usermask
	else:
	    maskmap = None

        grass.message(_("Note: The following 'consider changing' warnings may be ignored."))

        # clone current region
        grass.use_temp_region()
        grass.run_command('g.region', vect = vecttmp, align = input)

        # set the max number before segmantation
        segmax = 600
        if pointsnumber > segmax:
            grass.message(_("Using segmentation for interpolation..."))
            segmax = None
        else:
            grass.message(_("Using no segmentation for interpolation as not needed..."))
        # launch v.surf.rst    
	grass.message(_("Using RST interpolation..."))
	grass.run_command('v.surf.rst', input = vecttmp, elev = tmp1 + '_filled',
			zcol = 'value', tension = tension, smooth = smooth,
			maskmap = maskmap, segmax = segmax, flags = 'z')

	grass.message(_("Note: Above warnings may be ignored."))

    #check if method is different from rst to use r.resamp.bspline
    if method != 'rst':
	grass.message(_("Using %s bspline interpolation") % method)

        # clone current region
        grass.use_temp_region()
        grass.run_command('g.region', align = input)

	reg = grass.region()
	# launch r.resamp.bspline
	if grass.find_file(usermask, mapset = mapset)['file']:
	    grass.run_command('r.resamp.bspline', input = input, mask = usermask,
			    output = tmp1 + '_filled', method = method, 
			    se = 3 * reg['ewres'], sn = 3 * reg['nsres'], 
			    flags = 'n')
	else:
	    grass.run_command('r.resamp.bspline', input = input,
			    output = tmp1 + '_filled', method = method, 
			    se = 3 * reg['ewres'], sn = 3 * reg['nsres'], 
			    flags = 'n')

    # restore the real region
    grass.del_temp_region()

    # restoring user's mask, if present:
    if grass.find_file(usermask, mapset = mapset)['file']:
	grass.message(_("Restoring user mask (MASK)..."))
	grass.run_command('g.rename', quiet = True, rast = (usermask, 'MASK'))

    # patch orig and fill map
    grass.message(_("Patching fill data into NULL areas..."))
    # we can use --o here as g.parser already checks on startup
    grass.run_command('r.patch', input = (input,tmp1 + '_filled'), output = output, overwrite = True)

    grass.message(_("Filled raster map is: %s") % output)

    # write cmd history:
    grass.raster_history(output)

    grass.message(_("Done."))

if __name__ == "__main__":
    options, flags = grass.parser()
    atexit.register(cleanup)
    main()
