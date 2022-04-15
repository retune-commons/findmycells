from abc import ABC, abstractmethod
import os
import numpy as np
import pandas as pd
from pathlib import Path
import shutil
from PIL import Image
from typing import Tuple, List
import tempfile
import zarr

from skimage.measure import label
from skimage.segmentation import expand_labels
from skimage.io import imread, imsave

from .database import Database
from .utils import listdir_nohidden

"""

ToDos: 
 - when overwrite = True (and all file_ids are selected): deepflash configs should also be deleted and be recalculated again
 - semantic segmentation only as strategy

Currently remaining issues (old version):

1.  Due to low memory (Linux distribution), not all files can be processed by the df2 implementation at once (temp files in Linux system tmp directory).
    As work-arround, df2 perdictions will be done on individual batches ( = all single plane images of an original z-stack). 
    This should have no consequences for the regular "semantic" segmentations of df2, since the "stats" are calculated on all preprocessed images.
    After initial computation of these stats, however, df2 predictions (semantic & instance segmentations) are done on the individual batches.
    This allows to regularly clear all temp files and only consumes some GBs of disk space. The cellpose diameter, however, is calculated on base of all
    masks (semantic segmentations) that are present - and for the first batch, these are only the masks of all single planes of file_id 0000.
    
2.  Should make proper use of classes, like in preprocessing.py and quantifications.py. Probably one level less required here, though.
"""

class SegmentationObject:
    
    def __init__(self, database: Database, file_ids: List[str]) -> None:
        self.database = database
        self.file_ids = file_ids
        if 'batch_id' in database.file_infos.keys():
            self.batch_id = max(database.file_infos['batch_id']) + 1
        else:
            self.batch_id = 0


    def run_all_segmentation_steps(self) -> None:
        for segmentation_strategy in self.database.segmentation_strategies:
            self = segmentation_strategy().run(segmentation_object = self, step = self.database.segmentation_strategies.index(segmentation_strategy))
            
    
    def run_segmentation_step_by_index(self, positional_index: int) -> None:
        segmentation_strategy = self.database.segmentation_strategies[positional_index]
        step = self.determine_correct_step_index()
        self = segmentation_strategy().run(segmentation_object = self, step = step)
        
    
    def determine_correct_step_index(self):
        previous_segmentation_step_indices = []
        for key in self.database.file_infos.keys():
            if 'segmentation_step_' in key:
                step_index = int(key[key.rfind('_') + 1 :])
                previous_segmentation_step_indices.append(step_index)
        return max(previous_segmentation_step_indices) + 1
        
    
    def update_database(self) -> None:
        for file_id in self.file_ids:
            self.database.update_file_infos(file_id = file_id, updates = {'batch_id': self.batch_id}, preferred_empty_value = False)
            self.database.update_file_infos(file_id = file_id, updates = {'segmentation_completed': True})                   
        


class SegmentationStrategy(ABC):
    
    @abstractmethod
    def run(self, segmentation_object: SegmentationObject, step: int) -> SegmentationObject:
        # do preprocessing
        segmentation_object.database = self.update_database(database = segmentation_object.database, file_id = segmentation_object.file_ids, step = step)
        return segmentation_object
    
    @abstractmethod
    def update_database(self, database: Database, file_ids: List[str], step: int) -> Database:
        for file_id in file_ids:
            updates = dict()
            updates[f'segmentation_step_{str(step).zfill(2)}'] = 'SegmentationStrategyName'
            # Add additional information if neccessary
            database.update_file_infos(file_id = file_id, updates = updates)
        return database
    
    

class Deepflash2SemanticSegmentation(SegmentationStrategy):
    
    def run(self, segmentation_object: SegmentationObject, step: int) -> SegmentationObject:
        segmentation_object.databse = self.add_deepflash2_as_segmentation_tool(database = segmentation_object.database)
        self.copy_all_files_of_current_batch_to_temp_dir(database = segmentation_object.database, file_ids_in_batch = segmentation_object.file_ids)
        self.run_semantic_segmentations(database = segmentation_object.database)
        self.move_files(database = segmentation_object.database)
        self.delete_temp_files_in_sys_tmp_dir(database = segmentation_object.database)
        segmentation_object.database = self.update_database(database = segmentation_object.database, file_ids_in_batch = segmentation_object.file_ids, step = step)
        return segmentation_object
        
    def add_deepflash2_as_segmentation_tool(self, database: Database) -> Database:
        if hasattr(database, 'segmentation_tool_configs') == False:
            database.segmentation_tool_configs = {'df2': dict()}
        elif 'df2' not in database.segmentation_tool_configs.keys():
            database.segmentation_tool_configs['df2'] = dict()
        database.segmentation_tool_configs['df2']['n_models'] = len([elem for elem in listdir_nohidden(database.trained_models_dir) if elem.endswith('.pth')])
        database.segmentation_tool_configs['df2']['ensemble_path'] = database.trained_models_dir
        database.segmentation_tool_configs['df2']['stats'] = self.compute_stats(database = database)
        return database


    def compute_stats(self, database: Database) -> Tuple:
        from deepflash2.learner import EnsembleLearner
        expected_file_count = sum(database.file_infos['total_planes'])
        actual_file_count = len([image for image in listdir_nohidden(database.preprocessed_images_dir) if image.endswith('.png')])
        if actual_file_count != expected_file_count:
            raise ValueError('Actual and expected counts of preprocessed images don´t match.')
        ensemble_learner = EnsembleLearner(image_dir = database.preprocessed_images_dir.as_posix(), 
                                           ensemble_path = database.segmentation_tool_configs['df2']['ensemble_path'])
        stats = ensemble_learner.stats
        del ensemble_learner
        return stats


    def copy_all_files_of_current_batch_to_temp_dir(self, database: Database, file_ids_in_batch: List[str]) -> None:
        temp_copies_path = database.segmentation_tool_dir.joinpath('temp_copies_of_preprocessed_images')
        for file_id in file_ids_in_batch:
            files_to_segment = [filename for filename in listdir_nohidden(database.preprocessed_images_dir) if filename.startswith(file_id)]
            if len(files_to_segment) > 0:
                if temp_copies_path.is_dir() == False:
                    temp_copies_path.mkdir()
                for filename in files_to_segment:
                    filepath_source = database.preprocessed_images_dir.joinpath(filename)
                    shutil.copy(filepath_source.as_posix(), temp_copies_path.as_posix())


    def run_semantic_segmentations(self, database: Database):
        from deepflash2.learner import EnsembleLearner
        image_dir = database.segmentation_tool_dir.joinpath('temp_copies_of_preprocessed_images').as_posix()
        ensemble_learner = EnsembleLearner(image_dir = image_dir,
                                           ensemble_path = database.segmentation_tool_configs['df2']['ensemble_path'],
                                           stats = database.segmentation_tool_configs['df2']['stats'])
        ensemble_learner.get_ensemble_results(ensemble_learner.files, 
                                              zarr_store = database.segmentation_tool_temp_dir,
                                              export_dir = database.segmentation_tool_dir,
                                              use_tta = True)
        del ensemble_learner


    def move_files(self, database: Database) -> None:
        semantic_masks_path = database.segmentation_tool_dir.joinpath('masks')
        for semantic_mask_filename in listdir_nohidden(semantic_masks_path):
            filepath_source = semantic_masks_path.joinpath(semantic_mask_filename)
            shutil.move(filepath_source.as_posix(), database.semantic_segmentations_dir.as_posix())
        shutil.rmtree(database.segmentation_tool_dir.joinpath('temp_copies_of_preprocessed_images').as_posix())


    def delete_temp_files_in_sys_tmp_dir(self, database: Database) -> None:
        if hasattr(database, 'clear_temp_zarrs_from_sys_tmp'):
            # This was only tested under Linux as OS so far
            if database.clear_temp_zarrs_from_sys_tmp:
                temp_zarr_paths = [elem for elem in Path(tempfile.gettempdir()).iterdir() if 'zarr' in elem.name]
                for dir_path in temp_zarr_paths:
                    shutil.rmtree(dir_path.as_posix())       


    def update_database(self, database: Database, file_ids_in_batch: List[str], step: int) -> Database:
        for file_id in file_ids_in_batch:
            updates = dict()
            updates[f'segmentation_step_{str(step).zfill(2)}'] = 'Deepflash2SemanticSegmentation'
            updates['semantic_segmentations_done'] = True
            database.update_file_infos(file_id = file_id, updates = updates)
        return database



class LosslessConversionOfDF2SemanticSegToInstanceSegWithCP(SegmentationStrategy):
    
    def run(self, segmentation_object: SegmentationObject, step: int) -> SegmentationObject:
        segmentation_object.databse = self.add_cellpose_as_segmentation_tool(database = segmentation_object.database)        
        self.run_instance_segmentations(segmentation_object = segmentation_object)
        segmentation_object.database = self.update_database(database = segmentation_object.database, file_ids_in_batch = segmentation_object.file_ids, step = step)
        return segmentation_object
    
    
    def add_cellpose_as_segmentation_tool(self, database: Database) -> Database:
        if hasattr(database, 'segmentation_tool_configs') == False:
            database.segmentation_tool_configs = {'cp': dict()}
        elif 'cp' not in database.segmentation_tool_configs.keys():
            database.segmentation_tool_configs['cp'] = dict()
        for key, value in database.segmentation_configs['cellpose'].items():
            database.segmentation_tool_configs['cp'][key] = value
        if 'net_avg' not in database.segmentation_tool_configs['cp'].keys():
            database.segmentation_tool_configs['cp']['net_avg'] = True
        if 'model_type' not in database.segmentation_tool_configs['cp'].keys():
            database.segmentation_tool_configs['cp']['model_type'] = 'nuclei'        
        database.segmentation_tool_configs['cp']['diameter'] = self.compute_cellpose_diameter(semantic_masks_dir = database.semantic_segmentations_dir.as_posix())
        return database


    def compute_cellpose_diameter(self, semantic_masks_dir: Path) -> float:
        from deepflash2.models import get_diameters
        mask_paths = [semantic_masks_dir.joinpath(elem) for elem in listdir_nohidden(semantic_masks_dir)]
        masks_as_arrays = []
        for mask_as_image in mask_paths:
            with Image.open(mask_as_image) as image:
                masks_as_arrays.append(np.array(image))
        cellpose_diameter = get_diameters(masks_as_arrays)
        return cellpose_diameter


    def run_instance_segmentations(self, segmentation_object: SegmentationObject):
        database = segmentation_object.database
        zarr_group = zarr.open(database.segmentation_tool_temp_dir.as_posix(), mode='r')
        for image_filename in zarr_group['/smx'].__iter__():
            file_id = image_filename[:4]
            if file_id in segmentation_object.file_ids:
                if hasattr(database, 'verbose'):
                    if database.verbose:
                        print(f'Starting with {image_filename}')
                df2_softmax = zarr_group[f'/smx/{image_filename}'][..., 1]
                cp_mask = self.compute_cellpose_mask(df2_softmax = df2_softmax, 
                                                     model_type = database.segmentation_tool_configs['cp']['model_type'],
                                                     net_avg = database.segmentation_tool_configs['cp']['net_avg'],
                                                     diameter = database.segmentation_tool_configs['cp']['diameter'])
                df2_pred = np.zeros_like(df2_softmax)
                df2_pred[np.where(df2_softmax >= 0.5)] = 1            
                instance_mask = self.lossless_conversion_of_df2_semantic_to_instance_seg_using_cp(df2_pred = df2_pred, cp_mask = cp_mask)
                instance_mask = instance_mask.astype('uint16')
                filepath = database.instance_segmentations_dir.joinpath(image_filename)
                imsave(filepath, instance_mask, check_contrast=False)


    def compute_cellpose_mask(self, df2_softmax: np.ndarray, model_type: str, net_avg: bool, diameter: int) -> np.ndarray:
        from torch.cuda import empty_cache
        from cellpose import models
        empty_cache()
        model = models.Cellpose(gpu = True, model_type = model_type)
        cp_mask, _, _, _ = model.eval(df2_softmax, net_avg = net_avg, augment = True, normalize = False, diameter = diameter, channels = [0,0])
        empty_cache()
        return cp_mask


    def lossless_conversion_of_df2_semantic_to_instance_seg_using_cp(self, df2_pred: np.ndarray, cp_mask: np.ndarray) -> np.ndarray:
        lossless_converted_mask = np.zeros_like(df2_pred)
        labeled_df2_pred = label(df2_pred)
        unique_df2_labels = list(np.unique(labeled_df2_pred))
        unique_df2_labels.remove(0)
        for original_df2_label in unique_df2_labels:
            black_pixels_present = self.check_if_df2_label_is_fully_covered_in_cp_mask(df2_pred = labeled_df2_pred,
                                                                                       df2_label_id = original_df2_label,
                                                                                       cp_mask = cp_mask)                                                        
            if black_pixels_present:
                lossless_converted_mask = self.fill_entire_df2_label_area_with_instance_label(df2_pred = labeled_df2_pred, 
                                                                                              df2_label_id = original_df2_label, 
                                                                                              cp_mask = cp_mask,
                                                                                              converted_mask = lossless_converted_mask)
            else:
                cp_labels_within_df2_label = np.unique(cp_mask[np.where(labeled_df2_pred == original_df2_label)])
                tmp_cp_mask = cp_mask.copy()
                tmp_cp_mask[np.where(labeled_df2_pred != original_df2_label)] = 0
                for cp_label_id in cp_labels_within_df2_label:
                    next_label_id = lossless_converted_mask.max() + 1
                    lossless_converted_mask[np.where(tmp_cp_mask == cp_label_id)] = next_label_id
        return lossless_converted_mask


    def check_if_df2_label_is_fully_covered_in_cp_mask(self, df2_pred: np.ndarray, df2_label_id: int, cp_mask: np.ndarray) -> bool:
        cp_labels_within_df2_label = np.unique(cp_mask[np.where(df2_pred == df2_label_id)])
        if 0 in cp_labels_within_df2_label:
            black_pixels_present = True
        else:
            black_pixels_present = False
        return black_pixels_present


    def fill_entire_df2_label_area_with_instance_label(self, df2_pred: np.ndarray, df2_label_id: int, cp_mask: np.ndarray, converted_mask: np.ndarray) -> np.ndarray:
        cp_labels_within_df2_label = list(np.unique(cp_mask[np.where(df2_pred == df2_label_id)]))
        cp_labels_within_df2_label.remove(0)
        if len(cp_labels_within_df2_label) > 0:
            expanded_cp_mask = cp_mask.copy()
            expanded_cp_mask[np.where(df2_pred != df2_label_id)] = 0
            black_pixels_present, expansion_distance = True, 0
            while black_pixels_present:
                expansion_distance += 500
                expanded_cp_mask = expand_labels(expanded_cp_mask, distance = expansion_distance)
                black_pixels_present = self.check_if_df2_label_is_fully_covered_in_cp_mask(df2_pred = df2_pred,
                                                                                           df2_label_id = df2_label_id,
                                                                                           cp_mask = expanded_cp_mask)
            # remove all overflow pixels
            expanded_cp_mask[np.where(df2_pred != df2_label_id)] = 0
            for cp_label_id in cp_labels_within_df2_label:
                next_label_id = converted_mask.max() + 1
                converted_mask[np.where(expanded_cp_mask == cp_label_id)] = next_label_id
        else:
            next_label_id = converted_mask.max() + 1
            converted_mask[np.where(df2_pred == df2_label_id)] = next_label_id        
        return converted_mask


    def update_database(self, database: Database, file_ids_in_batch: List[str], step: int) -> Database:
        for file_id in file_ids_in_batch:
            updates = dict()
            updates[f'segmentation_step_{str(step).zfill(2)}'] = 'LosslessConversionOfDF2SemanticSegToInstanceSegWithCP'
            updates['instance_segmentations_done'] = True
            database.update_file_infos(file_id = file_id, updates = updates)
        return database


    
    



class Deepflash2SemanticAndInstanceSegmentation(SegmentationStrategy):
    
    def run(self, segmentation_object: SegmentationObject, step: int) -> SegmentationObject:
        if hasattr(segmentation_object.database, 'segmentation_tool_configs') == False:
            segmentation_object.database = self.initialize_deepflash2_as_segmentation_tool(database = segmentation_object.database)
        self.copy_all_files_of_current_batch_to_temp_dir(database = segmentation_object.database, file_ids_in_batch = segmentation_object.file_ids)
        segmentation_object.database = self.run_semantic_segmentations(database = segmentation_object.database)
        segmentation_object.database = self.run_instance_segmentations(database = segmentation_object.database)
        self.move_files(database = segmentation_object.database, file_ids_in_batch = segmentation_object.file_ids)
        self.delete_temporary_files_and_dirs(database = segmentation_object.database)
        segmentation_object.database = self.update_database(database = segmentation_object.database, file_ids_in_batch = segmentation_object.file_ids, step = step)
        return segmentation_object
    
    
    def initialize_deepflash2_as_segmentation_tool(self, database: Database) -> Database:
        database.segmentation_tool_configs = dict()
        database.segmentation_tool_configs['n_models'] = len([elem for elem in listdir_nohidden(database.trained_models_dir) if elem.endswith('.pth')])
        database.segmentation_tool_configs['ensemble_path'] = database.trained_models_dir
        database.segmentation_tool_configs['stats'] = self.compute_stats(database = database)
        return database
        
        
    def compute_stats(self, database: Database) -> Tuple:
        from deepflash2.learner import EnsembleLearner
        expected_file_count = sum(database.file_infos['total_planes'])
        actual_file_count = len([image for image in listdir_nohidden(database.preprocessed_images_dir) if image.endswith('.png')])
        if actual_file_count != expected_file_count:
            raise ValueError('Actual and expected counts of preprocessed images don´t match.')
        ensemble_learner = EnsembleLearner(image_dir = database.preprocessed_images_dir.as_posix(), 
                                           ensemble_path = database.segmentation_tool_configs['ensemble_path'])
        stats = ensemble_learner.stats
        del ensemble_learner
        return stats


    def copy_all_files_of_current_batch_to_temp_dir(self, database: Database, file_ids_in_batch: List[str]) -> None:
        temp_copies_path = database.segmentation_tool_dir.joinpath('temp_copies_of_preprocessed_images')
        for file_id in file_ids_in_batch:
            files_to_segment = [filename for filename in listdir_nohidden(database.preprocessed_images_dir) if filename.startswith(file_id)]
            if len(files_to_segment) > 0:
                if temp_copies_path.is_dir() == False:
                    temp_copies_path.mkdir()
                for filename in files_to_segment:
                    filepath_source = database.preprocessed_images_dir.joinpath(filename)
                    shutil.copy(filepath_source.as_posix(), temp_copies_path.as_posix())
    
    
    def run_semantic_segmentations(self, database: Database) -> Database:
        from deepflash2.learner import EnsembleLearner
        image_dir = database.segmentation_tool_dir.joinpath('temp_copies_of_preprocessed_images').as_posix()
        ensemble_learner = EnsembleLearner(image_dir = image_dir,
                                           ensemble_path = database.segmentation_tool_configs['ensemble_path'],
                                           stats = database.segmentation_tool_configs['stats'])
        ensemble_learner.get_ensemble_results(ensemble_learner.files, 
                                              zarr_store = database.segmentation_tool_temp_dir,
                                              export_dir = database.segmentation_tool_dir,
                                              use_tta = True)
        if 'df_ens' not in database.segmentation_tool_configs.keys():
            database.segmentation_tool_configs['df_ens'] = ensemble_learner.df_ens.copy()
        else:
            database.segmentation_tool_configs['df_ens'] = pd.concat([database.segmentation_tool_configs['df_ens'], ensemble_learner.df_ens.copy()])
        del ensemble_learner
        return database
        
    
    def run_instance_segmentations(self, database: Database) -> Database:
        from torch.cuda import empty_cache
        from deepflash2.learner import EnsembleLearner
        cellpose_diameter = self.get_cellpose_diameter(semantic_masks_dir = database.segmentation_tool_dir.joinpath('masks'))
        if 'cellpose_diameter_first_batch' not in database.segmentation_tool_configs.keys():
            database.segmentation_tool_configs['cellpose_diameter_first_batch'] = cellpose_diameter
            database.segmentation_tool_configs['cellpose_diameters_all_batches'] = list()
        database.segmentation_tool_configs['cellpose_diameters_all_batches'].append(cellpose_diameter)

        image_dir = database.segmentation_tool_dir.joinpath('temp_copies_of_preprocessed_images').as_posix()
        empty_cache()
        for row_id in range(database.segmentation_tool_configs['df_ens'].shape[0]):
            ensemble_learner = EnsembleLearner(image_dir = image_dir,
                                               ensemble_path = database.segmentation_tool_configs['ensemble_path'],
                                               stats = database.segmentation_tool_configs['stats'])
            df_single_row = database.segmentation_tool_configs['df_ens'].iloc[row_id].to_frame().T.reset_index(drop=True).copy()
            ensemble_learner.df_ens = df_single_row
            ensemble_learner.cellpose_diameter = database.segmentation_tool_configs['cellpose_diameter_first_batch']
            ensemble_learner.get_cellpose_results(export_dir = database.segmentation_tool_dir)
            del ensemble_learner
            empty_cache()
        return database
        
        
    def get_cellpose_diameter(self, semantic_masks_dir: Path) -> float:
        from deepflash2.models import get_diameters
        mask_paths = [semantic_masks_dir.joinpath(elem) for elem in listdir_nohidden(semantic_masks_dir)]
        masks_as_arrays = []
        for mask_as_image in mask_paths:
            with Image.open(mask_as_image) as image:
                masks_as_arrays.append(np.array(image))
        cellpose_diameter = get_diameters(masks_as_arrays)
        return cellpose_diameter        

    
    def move_files(self, database: Database, file_ids_in_batch: List[str]) -> None:
        semantic_masks_path = database.segmentation_tool_dir.joinpath('masks')
        for semantic_mask_filename in listdir_nohidden(semantic_masks_path):
            filepath_source = semantic_masks_path.joinpath(semantic_mask_filename)
            shutil.move(filepath_source.as_posix(), database.semantic_segmentations_dir.as_posix())
        instance_masks_path = database.segmentation_tool_dir.joinpath('cellpose_masks')
        for instance_mask_filename in listdir_nohidden(instance_masks_path):
            filepath_source = instance_masks_path.joinpath(instance_mask_filename)
            shutil.move(filepath_source.as_posix(), database.instance_segmentations_dir.as_posix())
            
    
    def delete_temporary_files_and_dirs(self, database: Database) -> None:
        if hasattr(database, 'clear_tmp_zarrs'):
            # This was only tested under Linux as OS so far
            if database.clear_tmp_zarrs:
                temp_zarr_paths = [elem for elem in Path(tempfile.gettempdir()).iterdir() if 'zarr' in elem.name]
                for dir_path in temp_zarr_paths:
                    shutil.rmtree(dir_path.as_posix())
                """
                temp_zarr_subdirs = [elem for elem in os.listdir('/tmp/') if 'zarr' in elem]
                if len(temp_zarr_subdirs) > 0:
                    for subdirectory in temp_zarr_subdirs:
                        shutil.rmtree(f'/tmp/{subdirectory}/')
                """
        shutil.rmtree(database.segmentation_tool_temp_dir.as_posix())       
        shutil.rmtree(database.segmentation_tool_dir.joinpath('temp_copies_of_preprocessed_images').as_posix())
        # Reset of df_ens is done in self.update_database() as it resembles an update of the database object
             

    def update_database(self, database: Database, file_ids_in_batch: List[str], step: int) -> Database:
        for file_id in file_ids_in_batch:
            updates = dict()
            updates[f'segmentation_step_{str(step).zfill(2)}'] = 'Deepflash2SemanticAndInstanceSegmentation'
            updates['semantic_segmentations_done'] = True
            updates['instance_segmentations_done'] = True
            database.update_file_infos(file_id = file_id, updates = updates)
        database.segmentation_tool_configs['df_ens'] = None
        return database