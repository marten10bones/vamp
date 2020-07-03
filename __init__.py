bl_info = {
    "name": "vamp_283",
    "author": "Chris Allen", 
    "version": (1, 1, 01),
    "blender": (2, 80, 0),
    "location": "View3D",
    "description": "VAMP: Vector Art Motion Processor. Removes back faces.",
    "warning": "Requires one object collection and one camera",
    "wiki_url": "https://github.com/zippy731/vamp",
    "category": "Development",
}

# GOOD TUT: https://blender.stackexchange.com/questions/57306/how-to-create-a-custom-ui


# updated from vamp_279
# based on https://theduckcow.com/2019/update-addons-both-blender-28-and-27-support/


import bpy
from bpy.props import IntProperty, EnumProperty, FloatProperty, BoolProperty, StringProperty, PointerProperty
from bpy.types import PropertyGroup, Operator, Panel, Scene
from bpy.app import driver_namespace
from bpy.app.handlers import frame_change_pre, frame_change_post, depsgraph_update_post
import bmesh
import mathutils
from mathutils import Vector, geometry, Matrix
from bpy_extras.object_utils import world_to_camera_view
from math import radians
import time
import random
from random import sample

#global sens # sensitivity - drives bracket vertex distance
global ray_dist # raycast distance
global cast_sens # raycast sensitivity, allows for offset of source vertex
global vert_limit # function slows exponentially for large vert counts. keep < 10k
global cam_x_scale
global cam_y_scale
global cam

global edge_sub_unit
global vamp_on 

class VampProperties(PropertyGroup):
    vamp_target: bpy.props.StringProperty(
        name = "VAMP Target",
        description = "Group name for VAMP",
        default = "VisibleObjects"
    )
    vamp_sil_mode: BoolProperty(
        name = "Ind Sil Mode",
        default = False,
        description = "Individual object silhouettes"
    )
    vamp_marked_mode: BoolProperty(
        name = "Freestyle",
        default = False,
        description = "Use Freestyle Edge Marks"
    )
    vamp_crease_mode: BoolProperty(
        name = "Creases",
        default = False,
        description = "Include Sharp Creases"
    )    
    vamp_crease_limit: IntProperty(
        name = "Lim",
        min = 0,
        max = 180,
        default = 160,
        description = "Crease Limit (Degrees)"
    )   
    vamp_cast_sensitivity: FloatProperty(
        name="Hit Test Offset",
        min = 0.005,
        max = 0.1,
        default = 0.02,
        precision = 3
    )
    vamp_raycast_dist: IntProperty(
        name = "Raycast Distance",
        min = 1,
        max = 100,
        description = "Hit testing distance.",
        default = 10
    )
    vamp_crop: BoolProperty(
        name = "Crop",
        default = True,
        description = "Limit output to camera frame?"
    )
    vamp_crop_options = [
        ("None","None","No cropping (fastest)",2),
        ("Front","Front","Forward facing only",1),
        ("Frame","Frame","Crop to camera frame",0)
    ]          
    vamp_crop_enum: EnumProperty(
        items = vamp_crop_options,
        name = "Crop",
        default = "None"
    )     
    vamp_scale: FloatProperty(
        name = "Output Scale",
        min = .25,
        max = 5,
        default = 1.0,
        description = "Resize final output",
    )
    vamp_denoise_pass: BoolProperty(
        name = "Denoise",
        default = False 
    )
    vamp_denoise_thresh: FloatProperty(
        name = "Limit",
        default = .05,
        min = .001,
        max = 10,
        precision = 3
    )    
    vamp_denoise_pct: FloatProperty(
        name = "Pct",
        default = 1.0,
        min = .02,
        max = 1.0
    )    
    vamp_vert_limit: IntProperty(
        name = "Vertex Limit",
        min = 1000,
        max = 1000000,
        description = "Vertex Count Limit.",
        default = 10000
    )
    vamp_subd_limit: IntProperty(
        name = "Cuts per Edge",
        min = 2,
        max = 100,
        description = "Max # of cuts",
        default = 3
    )
    vamp_edge_subdiv: FloatProperty(
        name = "Min length",
        min = 0.005,
        max = 2.0,
        default = 0.2,
        precision = 3
    )
    
# fixed parameters
vamp_on = False #switched off at beginning
vert_limit = 100000 #keep below 100k for reasonable performance. 
collapse_angle = 1.5 # radians, for dissolve function.
cam_x_scale = 4 #horiz aspect of camera.
cam_y_scale = 3 #horiz aspect of camera.

def item_check():
    global cam
    global scene
    global err_text
    scene = bpy.data.scenes[0]
    target_name = bpy.context.scene.vamp_params.vamp_target
    if bpy.data.collections.get(target_name) is not None:
        if len(bpy.data.collections[target_name].objects) > 0:
            if scene.camera is not None:
                cam = scene.camera
                return True
            else:
                print('no camera found')
                err_text = 'No camera found.'  
                return False
        else:
            print('no objects found in VAMP collection')
            err_text = 'No objects in VAMP collection.'  
            return False
    else:
        print('no object collection found')
        err_text = 'VAMP collection not found.'  
        return False
    
def clean_up_first():
    global empty_mesh
    global scene  
    target_name = bpy.context.scene.vamp_params.vamp_target    
    #now, create new empty objects 
    empty_mesh = bpy.data.meshes.new('empty_mesh') 
    scene = bpy.context.scene
    if bpy.data.objects.get('_slicedFinal') is None:
        newobj = bpy.data.objects.new(name='_slicedFinal',object_data = empty_mesh.copy())
        bpy.context.scene.collection.objects.link(newobj) # (2.8) Links object to scene master collection        
    if bpy.data.objects.get('_silhouetteFinal') is None:
        newobj = bpy.data.objects.new(name='_silhouetteFinal',object_data = empty_mesh.copy())
        bpy.context.scene.collection.objects.link(newobj)   
    if bpy.data.objects.get('_flatSliced') is None:
        newobj = bpy.data.objects.new(name='_flatSliced',object_data = empty_mesh.copy())
        bpy.context.scene.collection.objects.link(newobj)
    if bpy.data.objects.get('_flatSilhouette') is None:
        newobj = bpy.data.objects.new(name='_flatSilhouette',object_data = empty_mesh.copy())
        bpy.context.scene.collection.objects.link(newobj) 
    #now remove empty mesh
    bpy.data.meshes.remove(empty_mesh, do_unlink=True)
    return {'FINISHED'}

    
def join_bmeshes(bmesh_list):
    # combine multiple meshes into a single mesh
    joined_bmesh = bmesh.new()
    joined_bmesh.clear()
    for bm in bmesh_list:
        temp_mesh = bpy.data.meshes.new(name='temp_mesh')
        bm.to_mesh(temp_mesh)
        joined_bmesh.from_mesh(temp_mesh) # appends transformed data to the bmesh        
    # returns bmesh
    return joined_bmesh

def get_eval_mesh(obj):
    # evaluate object, which applies all modifiers
    #new method in 2.83, see https://docs.blender.org/api/current/bpy.types.Depsgraph.html
    #also see https://developer.blender.org/T64735#681264
    depsgraph = bpy.context.evaluated_depsgraph_get()
    object_eval = obj.evaluated_get(depsgraph)
    data_copy = bpy.data.meshes.new_from_object(object_eval)
    # also need to transform origin mesh, else they'll all be at 0,0,0
    the_matrix = obj.matrix_world        
    data_copy.transform(the_matrix) # transform mesh using source object transforms    
    
    return data_copy
    
    
def get_all_the_stuff():
    #outputs bm_all
    global bm_all
    global original_vert_count
    target_name = bpy.context.scene.vamp_params.vamp_target
    bm_all = bmesh.new()       
    for obj in bpy.data.collections[target_name].objects:
        # evaluate object, which applies all modifiers
        print(obj)
        TheType = obj.type
        print('TheType is ',TheType)
        if(TheType == 'MESH') or (TheType == 'CURVE'):
            data_copy=get_eval_mesh(obj)        
            bm_all.from_mesh(data_copy) # appends transformed data to the bmesh
    original_vert_count=(len(data_copy.edges)) # test for vert count. if too high, just quit.
    # bm_all now contains bmesh containing all data we need for next step
    # we will also use it later for BVHTree hit testing     
    return {'FINISHED'}

def get_marked_edges():
    #creates bm_marked
    #iterate thru all objects in group, find marked edges, 
    #create a single new BM comprising only marked edges
    #target_name = bpy.context.scene.vamp_params.vamp_target
    target_name = bpy.context.scene.vamp_params.vamp_target
    global bm_marked
    bm_marked = bmesh.new()
    bm_marked.clear()
    for obj in bpy.data.collections[target_name].objects:
        if(obj.type!='MESH'):
            #this only works for meshes. if not a mesh, skip.
            break
        # evaluate object, which applies all modifiers
        data_copy=get_eval_mesh(obj)
        counter = 0
        marked_list = []
        for e in data_copy.edges:
            if e.use_freestyle_mark is True:
                marked_list.append(counter)
            counter += 1             
        
        marked_edge_list = []
        if len(marked_list) > 0: 
            #if we found some, gen a list of edges & vertices
            for i in marked_list:
                edge_start = data_copy.edges[i].vertices[0]
                edge_end = data_copy.edges[i].vertices[1]
                this_edge = [edge_start,edge_end]
                marked_edge_list.append(this_edge)
    
            marked_vert_list = []
            for v in data_copy.vertices:
                marked_vert_list.append(v.co)            
            marked_face_list = []
            #build new mesh with marked data
            nu_marked_mesh = bpy.data.meshes.new(name='New Marked')
            nu_marked_mesh.from_pydata(marked_vert_list,marked_edge_list,marked_face_list)
            bm_marked.from_mesh(nu_marked_mesh) # appends transformed data to the bmesh  
        
        #1.02: added crease mode
        # if crease mode is active, also include creased edges
        if bpy.context.scene.vamp_params.vamp_crease_mode is True:
            creased_list = [] 
            bm_creased = bmesh.new()
            bm_creased.clear()
            bm_creased.from_mesh(data_copy)
            vamp_crease_limit = bpy.context.scene.vamp_params.vamp_crease_limit  #(convert to radians)
            uncreased_edges = []
            
            for e in bm_creased.edges:    
                if len(e.link_faces) == 2:
                    #make sure 2 faces exist..
                    angle=round(e.calc_face_angle_signed()*57.2958,1)
                    if abs(angle) < (180 - vamp_crease_limit):
                        # calc'd angle goes from zero (flat) to 179 (very acute)
                        # UI is based on more user friendly protractor style measure
                        uncreased_edges.append(e)
                        # if too flat, add into list to be deleted.
            bmesh.ops.delete(bm_creased, geom=uncreased_edges, context='EDGES') 
            temp_crease_mesh = bpy.data.meshes.new(name='temp_crease_mesh')
            bm_creased.to_mesh(temp_crease_mesh)
            bm_marked.from_mesh(temp_crease_mesh) # appends transformed data to the bmesh
            bm_creased.clear()
            
    # bm_marked now contains a single bm, with ONLY freestyle-marked edges
        
    return {'FINISHED'}      
    
def get_sep_meshes():
    # iterate the original list, generate a LIST of individual meshes for further analysis
    global sep_meshes
    target_name = bpy.context.scene.vamp_params.vamp_target
    sep_meshes = []  
    bm_all = bmesh.new() 
    bm_all.clear()
    for obj in bpy.data.collections[target_name].objects:
        if(obj.type != 'MESH' and obj.type != 'CURVE'):
            #this only works for meshes or curves. if not a mesh, skip.
            break
        bm_obj = bmesh.new()              
        # evaluate object, which applies all modifiers
        data_copy=get_eval_mesh(obj)
        bm_obj.from_mesh(data_copy) # appends transformed data to the bmesh
        sep_meshes.append(bm_obj)
    # sep_meshes now contains multiple bmeshes, one each for original objects.
    return {'FINISHED'}    

def rebuild_bmesh(bm):
    #Cleans up bmesh to join adjacent edges, remove mid-edge vertices
    #from https://blender.stackexchange.com/a/92419/49532
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.01)
    not_corners = [v for v in bm.verts if not is_corner(v)]
    bmesh.ops.dissolve_verts(bm, verts=not_corners)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    return(bm)
    
    
def empty_trash():
    #modified from: https://blender.stackexchange.com/a/132724/49532        
    trash = [o for o in bpy.data.meshes
            if o.users == 0]   
    while(trash):
        bpy.data.meshes.remove(trash.pop())
    
def is_corner(v):
    #from https://blender.stackexchange.com/a/92419/49532
    #MIN_ANGLE = radians(5)
    MIN_ANGLE = radians(.5)
    if len(v.link_edges) != 2:
        return False
    e1, e2 = v.link_edges[:]
    v1 = e1.other_vert(v).co - v.co
    v2 = e2.other_vert(v).co - v.co
    #print('v,v1,v2 are ',v.co,e1.other_vert(v).co,e2.other_vert(v).co)
    # need error trap if .co is same for any of these.
    return v1.angle(-v2) >= radians(MIN_ANGLE)


def is_endpoint(v):
    #not currently used
    #from https://blender.stackexchange.com/a/92419/49532
    if len(v.link_edges) == 1:
        return True
    else:
        return False
    
def denoise(bm):
    # remove edges below x threshold.  Can remove 100%, or random % sample
    global denoise_thresh
    #denoise_thresh = .5 #blender units
    denoise_thresh = bpy.context.scene.vamp_params.vamp_denoise_thresh    
    denoise_pct = bpy.context.scene.vamp_params.vamp_denoise_pct
    
    #if denoise is switched on, iterate thru bmesh edges, delete all which are < threshold length.
    noisy_edges = [e for e in bm.edges if e.calc_length() < denoise_thresh]
    # delete subset only.
    hitlist = int(len(noisy_edges)*denoise_pct)
    del_edges = sample(noisy_edges,hitlist)
    bmesh.ops.delete(bm, geom=del_edges, context='EDGES')
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=denoise_thresh)
    return(bm)

def distance(loc0,loc1):
    return (loc0-loc1).length    

def hit_test_bvh(originV,targetV,the_bvh):
    # hit test. bvh version is reliable
    cast_sens = bpy.context.scene.vamp_params.vamp_cast_sensitivity
    # hit test using bvh. 
    direction_vect = (targetV - originV) 
    offset_vect = direction_vect * (cast_sens)
    new_origin = originV + offset_vect # raycast with no offset fails (false positives). needs a buffer.
    direction = (direction_vect).normalized() # raycast expects a normalized vect
    ray_dist = bpy.context.scene.vamp_params.vamp_raycast_dist
    
    (loc,norm,indx,dist) = the_bvh.ray_cast(new_origin,direction,ray_dist)
    if loc is not None:
        return True # vert will be excluded, because it hit something.
    else:
        #vert might be visible, but still needs to be considered for cropping.
        scene = bpy.context.scene # sh/b redundant..
        co_ndc = world_to_camera_view(scene, cam, originV)    
        # if vert is a candidate, may also need to also check if in cam view
        if bpy.context.scene.vamp_params.vamp_crop_enum == 'None': 
            # camera crop turned off.  return hit check false
            return False
        elif bpy.context.scene.vamp_params.vamp_crop_enum == 'Front':
            if (co_ndc[2] < .01):#remove items immediately in front of plane also, due to distortion.
                return True # vert behind camera plane. Treate like a hit and exclude. 
            else:
                return False # vert in front of camera plane, presume visible 
        else:          
            #need to also test whether vert is within camera frame
            # confirm that vertex is visible, within view cone & range of camera
            if (co_ndc[0] >= 0) and (co_ndc[0] <= 1) and \
            (co_ndc[1] >= 0) and (co_ndc[1] <= 1) and \
            (co_ndc[2] > 0) and (co_ndc[2] <= ray_dist):
                return False # vert within camera view
            else:
                return True # vert outside of camera view, treat like a hit and exclude from all views    
    
                
def get_slicestuff(bm_test, bm_mask):
    # inputs: bm_test, bm_mask
    # outputs: bm_slice, bm_sil
    global cam
    #global bm_slice
    global bm_sil
    edge_sub_unit = bpy.context.scene.vamp_params.vamp_edge_subdiv # min length of subd
    subedge_limit = bpy.context.scene.vamp_params.vamp_subd_limit # max # of subd cuts

    # transform to world (in case it's parented to something else
    # per https://blender.stackexchange.com/questions/39677/how-do-you-get-an-objects-position-and-rotation-through-script
    cam_loc = cam.matrix_world.to_translation()
    
    # grab copy of bm_test for slicing
    bm_slicestuff = bm_test.copy()    
    bm_slicestuff.normal_update()
    bm_slicestuff.faces.ensure_lookup_table()
    bm_slicestuff.edges.ensure_lookup_table()
    bm_slicestuff.verts.ensure_lookup_table()  

    bmesh.ops.remove_doubles(bm_slicestuff, verts=bm_slicestuff.verts, dist=0.01)    
   
    edge_list = bm_slicestuff.edges

    cam_v0 = cam_loc #set as global earlier, includes matrix transform
    compare_edges = edge_list # make dup list for comparison later
    
    # this is only for bvh version. 
    the_bvh = mathutils.bvhtree.BVHTree.FromBMesh(bm_mask, epsilon = 0.0)
           
    the_edges=[] # all visible edges
    the_sil_edges=[] # silhouette only
    
    #iterate through all (test_edge) 
    for test_edge in edge_list:
		# subdivide edges based on edge_sub_unit
		# create sequence of edges that subdivides this edge n times              
        clean_edg_verts = []
        broken_edg_verts = []
        test_vert0 = test_edge.verts[0].co
        test_vert1 = test_edge.verts[1].co 
        test_edge_length = distance(test_vert0,test_vert1) 
        if test_vert0 == test_vert1:
            #ignore zero length edges. skip.
            break
        if test_edge_length == 0:
            break
        edge_sub_count = round(test_edge_length / edge_sub_unit)
        
        if edge_sub_count < 1:
            edge_sub_count = 1
        if edge_sub_count > subedge_limit:
            edge_sub_count = subedge_limit
        clean_edg_verts.append(test_vert0) # put in starting point for vertex seq        
        edge_sub_offset = (test_vert1 - test_vert0)/edge_sub_count
        if edge_sub_count > 1:
            for i in range(1, edge_sub_count-1):
                new_vert = test_vert0 + (i * edge_sub_offset)
                clean_edg_verts.append(new_vert)
        clean_edg_verts.append(test_vert1) # put in ending point for vertex seq
        
        # generate new edge list from vertices above
        for x in range (0,len(clean_edg_verts)-1):
            start_vert = clean_edg_verts[x]
            end_vert = clean_edg_verts[x+1]
            edge_pair=[start_vert,end_vert]
            cam_v0 = cam_loc
            # do hit testing to confirm both ends of small edge are visible
            # i.e. ray cast from point to camera doesn't hit anything                           
            # bvh raycasting follows
            # uses hit_test_bvh(originV,targetV,the_bvh)
            if hit_test_bvh(start_vert,cam_v0,the_bvh) is False and \
                hit_test_bvh(end_vert,cam_v0,the_bvh) is False:
                    the_edges.append(edge_pair)
                    # now test for silhouette:
                    # if cast AWAY from camera ALSO hits nothing, edge is part of silhouette
                    if hit_test_bvh(start_vert,(start_vert+(start_vert-cam_v0)),the_bvh) is False and \
                        hit_test_bvh(end_vert,(end_vert+(end_vert-cam_v0)),the_bvh) is False:
                            the_sil_edges.append(edge_pair)                            
    
    # now we've got final vertex pairs for edges, need to make a mesh of it.

    #first, make a set of unique vertices
    final_verts=[]
    for pairs in the_edges:
        vert1=pairs[0]
        if vert1 not in final_verts: 
            final_verts.append(vert1)
        vert2=pairs[1]
        if vert2 not in final_verts: 
            final_verts.append(vert2)
    
    #now iterate thru edge pairs the_edges, find vert indices from above
    final_edges=[]
    for pairs in the_edges:        
        vert0=pairs[0]
        vert_start=final_verts.index(vert0)
        vert1=pairs[1]
        vert_end=final_verts.index(vert1)       
        new_pair=[vert_start,vert_end]
        final_edges.append(new_pair)
        
    #repeating steps for silhouette: unique verts
    final_sil_verts=[]
    for pairs in the_sil_edges:
        vert1=pairs[0]
        if vert1 not in final_sil_verts: 
            final_sil_verts.append(vert1)
        vert2=pairs[1]
        if vert2 not in final_sil_verts: 
            final_sil_verts.append(vert2)
        
    final_sil_edges=[] #silhouette
    for pairs in the_sil_edges:        
        vert0=pairs[0]
        vert_start=final_sil_verts.index(vert0)
        vert1=pairs[1]
        vert_end=final_sil_verts.index(vert1)       
        new_pair=[vert_start,vert_end]
        final_sil_edges.append(new_pair)    

    final_faces=[] #empty list, for completeness
    
    # create new mesh, will be put into _sliceFinal
    nu_slice_mesh = bpy.data.meshes.new(name='New Slice')
    nu_slice_mesh.from_pydata(final_verts,final_edges,final_faces)    
    bm_slicetemp = bmesh.new()
    bm_slicetemp.from_mesh(nu_slice_mesh)
    
    fixed_bm_slice = rebuild_bmesh(bm_slicetemp)    
   
    # create new silhouette mesh, will be put into _silhouetteFinal
    nu_sil_mesh = bpy.data.meshes.new(name='New Silhouette')
    nu_sil_mesh.from_pydata(final_sil_verts,final_sil_edges,final_faces)  #too many verts, but they get deduped by rebuild below  
    bm_sil = bmesh.new()
    bm_sil.from_mesh(nu_sil_mesh)    
    fixed_bm_sil = rebuild_bmesh(bm_sil)

    return fixed_bm_slice, fixed_bm_sil  

def make_obj(bm_output,obj_name):
    obj_output = bpy.data.objects[obj_name]
    bm_output.to_mesh(obj_output.data)
    # Update view layer (added 2.8)
    layer = bpy.context.view_layer
    layer.update()    
    
    
def make_flattened(bm_output,flattened_name):
    #remap to flat plane for oscistudio to see
    global cam
    global vamp_scale
    vamp_scale = bpy.context.scene.vamp_params.vamp_scale
    # determine location based on xy cam scale
    flat_loc = Vector ((-0.5 * cam_x_scale * vamp_scale,-0.5 * cam_y_scale * vamp_scale,0))
    # first, make flatSliced    
    flat_sliced = bpy.data.objects[flattened_name]
    mat_world = flat_sliced.matrix_world
    
    # use bm_output, remap vertices
    FlatVerts = []    
    for v in bm_output.verts:
        co_ndc = world_to_camera_view(scene, cam, v.co)        
        v.co.x = co_ndc[0] * cam_x_scale * vamp_scale
        v.co.y = co_ndc[1] * cam_y_scale * vamp_scale
        v.co.z = 0
    bm_output.to_mesh(flat_sliced.data)
    flat_sliced.location = flat_loc 
    layer = bpy.context.view_layer
    layer.update()  
    return {'FINISHED'}

def main_routine(): 
    global cam
    global sil_mode
    global marked_mode
    global err_text

    sil_mode = bpy.context.scene.vamp_params.vamp_sil_mode
    # sil_mode decides whether silhouette is overall contour (of all objects combined,) or individual 
    # silhouettes per object.
    
    marked_mode = bpy.context.scene.vamp_params.vamp_marked_mode
    # marked_mode decides whether internal face detail is based on ALL visible edges or only FREESTYLE-MARKED visible edges
    
    start_time=time.time()   
    print('--- running main routine ---')
    
    # presumes item_check run first, to ensure data is there.
    clean_up_first()
    get_all_the_stuff() # puts all objects into a single bm_all
    print('original vert count is: ',original_vert_count) 
    vert_limit = bpy.context.scene.vamp_params.vamp_vert_limit
    if original_vert_count > vert_limit:
        #too many verts. quit.
        print('###########')
        print('I quit.  Vert limit is',vert_limit)
        print('This project is',original_vert_count,'verts, and would take too long.')        
        print('###########') 
        err_text = 'Sorry, too many verts' 
    else:
        get_sep_meshes() # gets separate meshes, for further processing
        
        sil_meshes = []
        if sil_mode is True:
            # individual sil mode, need to run thru twice
            for bm_single in sep_meshes:
                sil = get_slicestuff(bm_single,bm_single)
                sil_meshes.append(sil[1])
            bm_joined = join_bmeshes(sil_meshes)
            bm_sil = get_slicestuff(bm_joined,bm_all)[0]
        else:
            bm_sil = get_slicestuff(bm_all,bm_all)[1]   
        #bm_sil now contains bmesh with silhouette.
        
        #test for marked_mode. if true, use freestyle marked edges only.
        if marked_mode is True:
            get_marked_edges()
            bm_slice = get_slicestuff(bm_marked,bm_all)[0]
        else:
            bm_slice = get_slicestuff(bm_all,bm_all)[0]

        #clean up extraneous vertices
        fixed_bm_slice = rebuild_bmesh(bm_slice)
        fixed_bm_sil = rebuild_bmesh(bm_sil)

        if bpy.context.scene.vamp_params.vamp_denoise_pass:
            denoise(fixed_bm_slice)  
            denoise(fixed_bm_sil)              
        
        #output to 3d objects:
        make_obj(fixed_bm_slice,'_slicedFinal')
        make_obj(fixed_bm_sil,'_silhouetteFinal')
        
        # now remap to flat        
        make_flattened(fixed_bm_slice,'_flatSliced')        
        make_flattened(fixed_bm_sil,'_flatSilhouette')              
        
        #scene.update()  #old 2.79 version 
        # Update view layer (added 2.8)
        layer = bpy.context.view_layer
        layer.update()

        #free all the bmeshes
        bm_slice.free()
        bm_sil.free()
        fixed_bm_slice.free()
        fixed_bm_sil.free()
        
        #empty trash
        empty_trash()
        
        #UPDATE THE whole dg
        # per https://blender.stackexchange.com/a/140802/49532
        dg = bpy.context.evaluated_depsgraph_get() 
        dg.update()          
        bpy.context.view_layer.update()
        
    end_time=time.time()
    print('execution took ',end_time - start_time,' seconds.')
    print('original vert count was: ',original_vert_count)    
    return {'FINISHED'}

class OBJECT_OT_vamp_once(bpy.types.Operator):
    bl_label = "VAMP ONCE"
    bl_idname = "render.vamp_once"
    bl_description = "VAMP ONCE"       
    def execute(self, context):
        global cam
        global err_text
        if item_check():
            main_routine()
        else:
            print('item_check failed. :(  ') 
            err_phrase = 'Item check failed.  ' + err_text
            self.report({'WARNING'}, err_phrase)
        return {'FINISHED'}   

class OBJECT_OT_vamp_turn_on(bpy.types.Operator):
    global vamp_on
    bl_label = "Turn on VAMP"
    bl_idname = "render.vamp_turn_on"
    bl_description = "Turn on VAMP"        
    def execute(self, context):
        print("turning vamp on")
        global vamp_on
        scene = context.scene
        vampparams = scene.vamp_params
        print("Hello World")
        print("vamp_target: ", vampparams.vamp_target)

        vamp_on = True
        if item_check():
            main_routine()
        else:
            print('item_check failed. :(  ')  
            vamp_on = False                 
        return {'FINISHED'}

class OBJECT_OT_vamp_turn_off(bpy.types.Operator):
    bl_label = "Turn off VAMP"
    bl_idname = "render.vamp_turn_off"
    bl_description = "Turn off VAMP"        
    def execute(self, context):
        print("turning vamp off")
        global vamp_on
        vamp_on = False                 
        return {'FINISHED'}

class Vamp_PT_Panel(bpy.types.Panel):
    #Creates a Panel in the render context of the properties editor
    bl_label = "VAMP Settings"
    bl_idname = "VAMP_PT_layout"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = "render"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        layout = self.layout
        layout.label(text="", icon="OUTLINER_OB_LATTICE")
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        vampparams = scene.vamp_params
        
        row = layout.row()
        #row.scale_y = 2.0
        sub = row.row()
        sub.scale_x = 2.0
        sub.scale_y = 2.0        
        
        #VAMP ON/OFF
        if vamp_on is True:
            sub.operator("render.vamp_turn_off", text="Turn Off VAMP")            
        else:   
            sub.operator("render.vamp_turn_on", text="Turn On VAMP")
                

        sub.scale_y = 2.0   
        sub.operator("render.vamp_once", text="VAMP ONCE")  
      
        layout.separator()
        
        #user options
        row = layout.row(align=True)
        row.prop(vampparams, "vamp_sil_mode")
        row.prop(vampparams, "vamp_crop_enum")
        
        row = layout.row(align=True)        
        row.prop(vampparams, "vamp_marked_mode")
        row.prop(vampparams, "vamp_crease_mode")
        row.prop(vampparams, "vamp_crease_limit")  
        
        layout.prop(vampparams, "vamp_target")
        layout.prop(vampparams, "vamp_scale")
        layout.prop(vampparams, "vamp_vert_limit")
        
        row = layout.row(align=True)        
        row.prop(vampparams, "vamp_subd_limit")
        row.prop(vampparams, "vamp_edge_subdiv")       
        
        row = layout.row(align=True)
        row.prop(vampparams, "vamp_raycast_dist")
        row.prop(vampparams, "vamp_cast_sensitivity")

        row = layout.row(align=True)
        row.prop(vampparams, "vamp_denoise_pass")
        row.prop(vampparams, "vamp_denoise_thresh")
        row.prop(vampparams, "vamp_denoise_pct")          


def vamp_handler(scene):    
    global vamp_on
    global cam
    if vamp_on is True:
        if item_check():
            main_routine()
        else:
            print('item_check failed. :(  ')      

classes = (OBJECT_OT_vamp_once,OBJECT_OT_vamp_turn_on,OBJECT_OT_vamp_turn_off,VampProperties,Vamp_PT_Panel)          

def register():
    #polite app handler management, per:
    #    https://oktomus.com/posts/2017/safely-manage-blenders-handlers-while-developing/
    handler_key = 'VAMP_283_KEY'
    if handler_key in driver_namespace:
        if driver_namespace[handler_key] in frame_change_pre:
            frame_change_pre.remove(driver_namespace[handler_key])
        del driver_namespace[handler_key]
    bpy.app.handlers.frame_change_pre.append(vamp_handler) 
    driver_namespace[handler_key] = vamp_handler
    
    # need better handler handling, like this:
    #    https://oktomus.com/posts/2017/safely-manage-blenders-handlers-while-developing/
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.vamp_params = PointerProperty(type=VampProperties)  #old 2.79 version 
 
def unregister():
    #del vamp_params     
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)    

if __name__ == "__main__":
   register()
