import seaborn as sns
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from IPython.display import HTML, Javascript

import sys
sys.path.append('../inverse_rendering/')
from general_imports import *
from tqdm import tqdm as tqdm_file
import argparse
import string
import random
import warnings
warnings.filterwarnings("ignore")

from numpy import asarray
from numpy import exp
from numpy import sqrt
from numpy import cos
from numpy import e
from numpy import pi
from numpy import argsort
from numpy.random import randn
from numpy.random import rand
from numpy.random import seed
import json

alphanumeric_key = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
print("Key is: %s"%alphanumeric_key)

##### Load Model #####
model_path = '../training_models/saved_models/resnet18_v7_normalized_final.pt'
loaded_model = torch.load(model_path)
softmax_layer = nn.Softmax()
shorter_model = nn.Sequential(*list(loaded_model.children())[:-1])
shorter_model.cuda();

#### Load Shapenet Category etc. ####
with open('../training_models/shapenet_class_num_to_class_name.p','rb') as F:
    shapenet_class_num_to_class_name = pickle.load(F)
with open('../training_models/shapenet_id_to_class_num.p','rb') as F:
    shapenet_id_to_class_num = pickle.load(F)

##### Randomization Functions ######

RADIUS_MIN = 8.0
RADIUS_MAX = 14.0
MIN_NUM_LIGHTS = 1
MAX_NUM_LIGHTS = 4

RADIUS_MIN_CAM = 0.5
RADIUS_MAX_CAM = 8.0

def generate_uniform_on_sphere(num_points, radius):
    points = []
    for i in range(num_points):
        X = np.random.normal()
        Y = np.random.normal()
        Z = np.random.normal()

        vector = np.array([X,Y,Z])
        point = list(radius*vector/np.linalg.norm(vector))
        points.append(point)
    return points
def get_cam_position(radius_min, radius_max):
    random_radius = random.uniform(radius_min, radius_max)
    cam_point = generate_uniform_on_sphere(1, random_radius)[0]
    cam_point = torch.tensor(cam_point).float()

    return cam_point
def get_positions(min_num_lights, max_num_lights, radius_min, radius_max):
    num_lights = random.choice(range(min_num_lights, max_num_lights + 1))
    light_positions = []

    for num in range(num_lights):
        random_radius = random.uniform(radius_min, radius_max)
        light_point = generate_uniform_on_sphere(1, random_radius)[0]
        light_point = torch.tensor(light_point).float()
        light_positions.append(light_point)

    return light_positions
def get_random_intensity():
    light_intensity = torch.tensor([random.uniform(0,1), \
                                    random.uniform(0,1), random.uniform(0,1)]).float()
    return light_intensity
def get_random_reflectance():
    specular_reflectance = torch.tensor([random.uniform(0,1), \
                                    random.uniform(0,1), random.uniform(0,1)], device = pyredner.get_device()).float()
    return specular_reflectance
def get_random_look_at(radius):
    K = 0.3
    look_at = torch.tensor([random.uniform(0,K*radius), random.uniform(0,K*radius), random.uniform(0,K*radius)]).float()
    return look_at
def get_random_scene_params(model_file):
    ### Random Camera Settings ###
    camera_position = get_cam_position(RADIUS_MIN_CAM, RADIUS_MAX_CAM)
    cam_radius = torch.sqrt(camera_position[0]**2 + camera_position[1]**2 + camera_position[2]**2).item()
    cam_look_at = get_random_look_at(cam_radius)
    fov = torch.tensor(random.uniform(35,100))
    cam_up = torch.tensor([random.uniform(-1,1), random.uniform(-1,1), random.uniform(-1,1)])
    initial_camera_params = {'camera_position': camera_position,
                             'cam_look_at': cam_look_at,
                             'fov': fov,
                             'cam_up': cam_up}


    ### Random Light Settings ###
    all_light_positions = get_positions(MIN_NUM_LIGHTS, MAX_NUM_LIGHTS, RADIUS_MIN, RADIUS_MAX)
    all_light_look_ats = [get_random_look_at(cam_radius) for i in all_light_positions]
    all_light_intensities = [get_random_intensity() for i in all_light_positions]
    all_light_sizes = [torch.tensor([random.uniform(0.1,5.0), random.uniform(0.1, 5.0)]) for i in all_light_positions]
    initial_light_params = {'all_light_positions': all_light_positions,
                            'all_light_look_ats': all_light_look_ats,
                            'all_light_intensities': all_light_intensities,
                            'all_light_sizes': all_light_sizes}

    #### Material ####
    diffuse_material = pyredner.Material(diffuse_reflectance = torch.tensor([1.0, 1.0, 1.0], \
                                        device='cuda:0'), two_sided = True)
    material_settings = {'diffuse_material':diffuse_material}

    scene_params = [model_file, initial_camera_params, initial_light_params, material_settings]
    return scene_params
def show_inputs(inp, save_path = False, title='No Title'):
    plt.imshow(inp[0].cpu().permute(1,2,0).int())
    plt.title(title)
    plt.axis('off')
    if save_path != False:
        plt.savefig(save_path)
    else:
        plt.show()
def render_input(scene):
    img = pyredner.render_pathtracing(scene = scene, num_samples = 256, seed = 1, use_secondary_edge_sampling = False)
    img = torch.clamp(img, min = 0.00000001)
    img = torch.pow(img, 1.0/2.2)
    img = img*255/torch.max(img)
    inputs = img.permute(2,0,1).unsqueeze(0)
    return inputs
def spherical_to_cartesian(r,theta,phi):
    theta_rad = theta*3.14/180
    phi_rad = phi*3.14/180

    x = r * torch.sin(phi_rad) * torch.cos(theta_rad)
    y = r * torch.sin(phi_rad) * torch.sin(theta_rad)
    z = r * torch.cos(phi_rad)
    out =  torch.stack([x,y,z])
    return out
def load_geometry(model_file, geometry, mat):
    if geometry:
        obj_model_all = model_file
        obj_model = [i for i in obj_model_all if len(i.vertices)>0]
    else:
        obj_model_all = pyredner.load_obj(model_file, return_objects=True)
        obj_model = [i for i in obj_model_all if len(i.vertices)>0]

    for part in obj_model:
        part.material = mat

    return obj_model
def optimize_flags(obj):
    if type(obj) == list:
        for o in obj:
            o.requires_grad = True
    else:
        obj.requires_grad = True
    return obj
def setup_scene(scene_params):

    model_file, camera_params, light_params, material_settings = scene_params
    obj_model = load_geometry(model_file, False, material_settings['diffuse_material'])

    #### Camera Setup ####
    scene_cam = pyredner.automatic_camera_placement(obj_model, resolution = (224, 224),
                                                   fov = torch.tensor([camera_params['fov']]),
                                                   up = camera_params['cam_up'],
                                                   look_at = camera_params['cam_look_at'])
    scene_cam.position = camera_params['camera_position']

    #### Lights Setup ####
    scene_lights = []
    num_lights = len(light_params['all_light_positions'])
    for i in range(num_lights):
        scene_light = pyredner.generate_quad_light(position = light_params['all_light_positions'][i],
                                     look_at = light_params['all_light_look_ats'][i],
                                     size = light_params['all_light_sizes'][i],
                                     intensity = light_params['all_light_intensities'][i],
                                     directly_visible = False)
        scene_lights.append(scene_light)

    all_objects = obj_model + scene_lights
    scene = pyredner.Scene(objects = all_objects, camera = scene_cam)

    return scene
def start_up(scene_params, optimized_params):
    model_file, camera_params, light_params, material_settings = scene_params
    variables = []
    var_names_list = []
    for param in optimized_params:
        if param in camera_params.keys():
            optimize_flags(camera_params[param])
            if type(camera_params[param]) == list:
                variables.extend(camera_params[param])
            else:
                variables.append(camera_params[param])
        elif param in light_params.keys():
            optimize_flags(light_params[param])
            if type(light_params[param]) == list:
                variables.extend(light_params[param])
            else:
                variables.append(light_params[param])

    scene_params = [model_file, camera_params, light_params, material_settings]
    scene = setup_scene(scene_params)

    return scene, variables
def get_random_3d_model():
    model_files_pickle = '../rendering/shapenet_model_subsets/categories_10_models_10.pkl'
    with open(model_files_pickle, 'rb') as F:
        model_files = pickle.load(F)
    random_category = random.choice(list(model_files.keys()))
    random_instance = random.choice(model_files[random_category]).split('/')[7]
    model_file = '%s/ShapeNetCore.v2/%s/%s/models/model_normalized.obj'%(user_root_dir, random_category, random_instance)
    print('Chosen model is a %s'%shapenet_class_num_to_class_name[shapenet_id_to_class_num[random_category]])
    category_num = shapenet_id_to_class_num[random_category]
    print('Category num is %s'%category_num)
    return model_file, category_num, random_category, random_instance
def perturbation_vector(factor_len, perturb_percent = 1):
    if factor_len == 0:
        factor_len = 1
    vec = torch.tensor([random.uniform(-perturb_percent/100,perturb_percent/100) for i in range(factor_len)])
    return 1 + vec
def random_perturbed_params(scene_params, perturb_percent = 1):
    new_scene_params = [0,0,0,0]
    new_scene_params[0] = scene_params[0]

    new_scene_params[1] = {}
    for key in scene_params[1].keys():
        new_scene_params[1][key] = scene_params[1][key].clone() * perturbation_vector(scene_params[1][key].dim(), perturb_percent)

    new_scene_params[2] = {}
    for key in scene_params[2].keys():
        new_scene_params[2][key] = [i.clone() * perturbation_vector(i.dim(), perturb_percent) for i in scene_params[2][key]]

    new_scene_params[3] = scene_params[3]
    return new_scene_params
def render_and_predict(scene_params, optimized_params):
    scene, variables = start_up(scene_params, optimized_params)
    inputs = render_input(scene)
    inputs = inputs.cuda()
    rendered_inputs = inputs.clone()
    inputs = inputs/255.0
    im_means = torch.mean(inputs).unsqueeze(0).unsqueeze(1).unsqueeze(1).unsqueeze(1)
    im_stds = torch.std(inputs).unsqueeze(0).unsqueeze(1).unsqueeze(1).unsqueeze(1)
    inputs_ = (inputs - im_means)/im_stds
    outputs = softmax_layer(loaded_model(inputs_))
    prediction = torch.argmax(outputs).item()
    return prediction, rendered_inputs
def create_folder(folder):
    if not os.path.isdir(folder):
        os.mkdir(folder)
def clone_scene_params(scene_params):
    original_scene_params = [0,0,0,0]
    original_scene_params[0] = scene_params[0]

    original_scene_params[1] = {}
    for key in scene_params[1].keys():
        original_scene_params[1][key] = scene_params[1][key].clone()

    original_scene_params[2] = {}
    for key in scene_params[2].keys():
        original_scene_params[2][key] = [i.clone() for i in scene_params[2][key]]

    original_scene_params[3] = scene_params[3]
    return original_scene_params
def check_in_range(scene_params):
    if scene_params[0] == 0:
        return False
    cam_radius = torch.norm(scene_params[1]['camera_position'])
    radius_check = RADIUS_MIN_CAM <= cam_radius <= RADIUS_MAX_CAM
    look_at_check = torch.sum(scene_params[1]['cam_look_at'] < cam_radius*0.3).item() == 3
    return radius_check and look_at_check
def get_in_range(range_low, range_high):
    return (range_low + rand(1) * (range_high - range_low))[0]

def get_new_candidate(original_scene_params):
    candidate_params = [0,0,0,0]
    while check_in_range(candidate_params) == False:
        candidate_params[0] = original_scene_params[0]
        candidate_params[1] = {}
        candidate_params[1]['camera_position'] = torch.tensor([get_in_range(RADIUS_MIN_CAM, RADIUS_MAX_CAM), get_in_range(RADIUS_MIN_CAM, RADIUS_MAX_CAM), get_in_range(RADIUS_MIN_CAM, RADIUS_MAX_CAM)])
        radius = torch.norm(candidate_params[1]['camera_position']).item()
        candidate_params[1]['cam_look_at'] = torch.tensor([get_in_range(-0.2*radius, 0.2*radius), get_in_range(-0.2*radius, 0.2*radius), get_in_range(-0.2*radius, 0.2*radius)]).float()
        candidate_params[1]['fov'] = original_scene_params[1]['fov']
        candidate_params[1]['cam_up'] = torch.tensor([get_in_range(-1,1), get_in_range(-1,1), get_in_range(-1,1)]).float()

        candidate_params[2] = original_scene_params[2]
        candidate_params[3] = original_scene_params[3]
    return candidate_params
def update_pop_member(original_scene_params, step_size):
    candidate_params = [0,0,0,0]
    while check_in_range(candidate_params) == False:
        candidate_params[0] = original_scene_params[0]
        candidate_params[1] = {}
        candidate_params[1]['camera_position'] = original_scene_params[1]['camera_position'] + torch.rand(3)*step_size
        candidate_params[1]['cam_look_at'] = original_scene_params[1]['cam_look_at'] + torch.rand(3)*step_size
        candidate_params[1]['cam_look_at'] = candidate_params[1]['cam_look_at'].float()
        candidate_params[1]['fov'] = original_scene_params[1]['fov']
        candidate_params[1]['cam_up'] = original_scene_params[1]['cam_up'] + torch.rand(3)*step_size
        candidate_params[1]['cam_up'] = candidate_params[1]['cam_up'].float()
        candidate_params[2] = original_scene_params[2]
        candidate_params[3] = original_scene_params[3]
    return candidate_params

def objective(scene_params, optimized_params, neuron_num = None):
    scene, variables = start_up(scene_params, [])
    inputs = render_input(scene)
    inputs = inputs.cuda()
    rendered_inputs = inputs.clone()
    inputs = inputs/255.0
    im_means = torch.mean(inputs).unsqueeze(0).unsqueeze(1).unsqueeze(1).unsqueeze(1)
    im_stds = torch.std(inputs).unsqueeze(0).unsqueeze(1).unsqueeze(1).unsqueeze(1)
    inputs_ = (inputs - im_means)/im_stds
    outputs = shorter_model(inputs_)
    if neuron_num is None:
        selective_neurons = torch.argsort(outputs[0].view(512,-1).squeeze(1))[-1]
        selected_act_firing = outputs[0].view(512,-1).squeeze(1)[selective_neurons]
        return selective_neurons, selected_act_firing
    else:
        loss = torch.sum(outputs[0].view(512,-1).squeeze(1)[neuron_num]).item()
    return loss



folder = '/om5/user/smadan/differentiable_graphics_ml/other_optimization_methods/cma_pre_final_maximize/'
create_folder(folder)

model_file, category_num, category, instance = get_random_3d_model()
optimized_params = []
curr_pred = -1
while curr_pred != category_num:
    scene_params = get_random_scene_params(model_file)
    original_scene_params = clone_scene_params(scene_params)
    curr_pred, _ = render_and_predict(scene_params, [])
selected_neuron, selected_neuron_act = objective(scene_params, [], None)
selected_neuron = selected_neuron.item()
selected_neuron_act = selected_neuron_act
with open('../activations_brute_force/neuron_instance_to_grid_activations_resnet18_v7_test.json','r') as F:
    acts = json.load(F)
min_brute_force = np.min(acts['pre_final_layer'][str(selected_neuron)][category][instance])
max_brute_force = np.max(acts['pre_final_layer'][str(selected_neuron)][category][instance])
print('Maximum from brute force is :%s'%max_brute_force)
#### CMA hyperparams #####
lam = 10
mu = 5
step_size = 0.01
best, best_eval = None, 1
all_best_evals = []

#### Make initial Population
n_children = int(lam / mu)
population = []


for _ in range(lam):
    candidate = get_random_scene_params(model_file)
    population.append(candidate)

found_adv = False
past_population = []
past_scores = []
for epoch in range(100):
    if found_adv == True:
        break

    # Measure Current Population
    scores = []
    print('Measuring current population...')
    for c in tqdm_file(population):
        try:
            score = objective(c, optimized_params, selected_neuron)
            scores.append(score)
        except:
            scores.append(1e+10)
    print('Adding parent scores...')
    scores.extend(past_scores)
    population.extend(past_population)
    # print('Scores are: %s'%scores)

    # Get children for best members of population
    selected = np.argsort(scores)[-mu:]
    children = list()
    print('Getting children...')
    selected_scores = [scores[i] for i in selected]
    print('scores of selected members: %s'%selected_scores)
    for i in tqdm_file(selected):
        if scores[i] > best_eval:
            print('Score is %s'%scores[i])
            best, best_eval = population[i], scores[i]
            print('Best: %.5f. Brute force best was: %s' %(best_eval, max_brute_force))
            if best_eval > max_brute_force:
                print('Found new maxima!')
                found_adv = True
                break
        for child_num in range(n_children):
            child = update_pop_member(population[i], step_size)
            children.append(child)
    past_population = population
    past_scores = scores
    population = children

# with open('%s/%s_adv.p'%(folder, alphanumeric_key),'wb') as F:
#     pickle.dump(best, F)
info_to_save = {}
info_to_save['model_file'] = model_file
info_to_save['maxima_setting'] = best
info_to_save['found_maxima'] = found_adv

print('New maxima found. Best loss=%s'%best_eval)
with open('%s/Experiment_%s_info.p'%(folder, alphanumeric_key),'wb') as F:
    pickle.dump(info_to_save, F)
