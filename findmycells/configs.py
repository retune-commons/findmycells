# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/00_configs.ipynb.

# %% auto 0
__all__ = ['ProjectConfigs', 'DefaultConfigs', 'GUIConfigs']

# %% ../nbs/00_configs.ipynb 2
from pathlib import Path, PosixPath
from typing import Optional, Dict, Any, List, Tuple, Callable, Union
from traitlets.traitlets import MetaHasTraits as WidgetType
import ipywidgets as w
from ipyfilechooser import FileChooser
import os
import inspect
import pickle
from datetime import datetime

import findmycells

# %% ../nbs/00_configs.ipynb 6
class ProjectConfigs:
    
    
    def __init__(self, root_dir: PosixPath) -> None:
        assert type(root_dir) == PosixPath, '"root_dir" must be pathlib.Path referring to an existing directory.'
        assert root_dir.is_dir(), '"root_dir" must be pathlib.Path referring to an existing directory.'
        self.root_dir = root_dir
        self.load_available_processing_modules()
        self._load_available_strategies_and_objects()
        self._load_default_configs_of_available_data_readers()
            
    
    def load_available_processing_modules(self) -> None:
        available_processing_modules = {}
        for module_name, module in inspect.getmembers(findmycells, inspect.ismodule):
            if hasattr(module, 'specs') & hasattr(module, 'strategies'):
                available_processing_modules[module_name] = module
        setattr(self, 'available_processing_modules', available_processing_modules)
        

    def _load_default_configs_of_available_data_readers(self) -> None:
        default_configs_of_available_data_readers = {}
        for reader_module_name, reader_module in inspect.getmembers(findmycells.readers, inspect.ismodule):
            for variable_name, default_reader_configs in inspect.getmembers(reader_module):
                if variable_name == 'DEFAULT_READER_CONFIGS':
                    default_configs_of_available_data_readers[reader_module_name] = default_reader_configs
        setattr(self, 'default_configs_of_available_data_readers', default_configs_of_available_data_readers)
        
    
    def _load_available_strategies_and_objects(self) -> None:
        available_processing_objects = {}
        available_processing_strategies = {}
        for processing_type, module in self.available_processing_modules.items():
            for class_name, obj in inspect.getmembers(module.specs, inspect.isclass):
                if (class_name.endswith('Object')) & (class_name != 'ProcessingObject'):
                    available_processing_objects[processing_type] = obj
            strats = []
            for class_name, obj in inspect.getmembers(module.strategies, inspect.isclass):
                if class_name.endswith('Strat'):
                    strats.append(obj)
            available_processing_strategies[processing_type] = strats
        self.available_processing_objects = available_processing_objects
        self.available_processing_strategies = available_processing_strategies
            
            
    def add_processing_step_configs(self, processing_step_id: str, configs: Optional[Dict[str, Any]]=None) -> None:
        assert processing_step_id in self.available_processing_modules.keys(), '"processing_step_id" has to match with an available processing module!'
        if configs == None:
            configs = {}
        processing_obj = self.available_processing_objects[processing_step_id]()
        processing_obj.default_configs.assert_user_input(user_input = configs)
        configs = processing_obj.default_configs.fill_user_input_with_defaults_where_needed(user_input = configs)
        setattr(self, processing_step_id, configs)
        
    
    def add_reader_configs(self, reader_type: str, configs: Optional[Dict[str, Any]]=None) -> None:
        assert reader_type in self.default_configs_of_available_data_readers.keys(), '"reader_type" has to match with an available reader module!'
        if configs == None:
            configs = {}
        self.default_configs_of_available_data_readers[reader_type].assert_user_input(user_input = configs)
        configs = self.default_configs_of_available_data_readers[reader_type].fill_user_input_with_defaults_where_needed(user_input = configs)
        setattr(self, reader_type, configs)

# %% ../nbs/00_configs.ipynb 7
class DefaultConfigs:
    
    """
    This class has to be specified as an attribute in several classes throughout findmycells
    and allows / ensures that each novel class defines its own set of default config values. 
    Moreover, the 'valid_types' dictionary also defines which types of values are allowed.
    """
    
    def __init__(self, 
                 default_values: Dict[str, Any], # Keys are identifier of config options, values the corresponding default value
                 valid_types: Dict[str, List[type]], # Keys must match with keys of "default_values", values are lists of allowed types
                 valid_value_ranges: Optional[Dict[str, Tuple]]=None, # Required for every config option that allows floats or integers. Keys must match with keys of "default_values". Expected format: (start_idx, end_idx) or (start_idx, end_idx, step_size)
                 valid_value_options: Optional[Dict[str, Tuple]]=None, # Keys must match with keys of "default_values". Expected format: ('option_a', 'option_b', ...)
                ) -> None:
        self._assert_valid_input(default_values, valid_types, valid_value_ranges, valid_value_options)
        self.values = default_values
        self.valid_types = valid_types
        if valid_value_ranges == None:
            self.valid_ranges = {}
        else:
            self.valid_ranges = valid_value_ranges
        if valid_value_options == None:
            self.valid_options = {}
        else:
            self.valid_options = valid_value_options
    
    
    def get_step_size_if_present(self, key: str) -> Optional[Union[int, float]]:
        step_size = None
        if key in self.valid_ranges.keys():
            if len(self.valid_ranges[key]) == 3:
                step_size = self.valid_ranges[key][2]
        return step_size
    
    
    def get_options_if_present(self, key: str) -> Optional[Tuple[str]]:
        if key in self.valid_options.keys():
            options = self.valid_options[key]
        else:
            options = None
        return options
    
    
    def assert_user_input(self, user_input: Dict[str, Any]) -> None:
        assert type(user_input) == dict, '"user_input" has to be a dictionary!'
        for key, value in user_input.items():
            assert key in self.values.keys(), f'User input key "{key}" does not match with default value keys!'
            assert type(value) in self.valid_types[key], f'Value type for {key} not listed in valid types!'
            if type(value) in [int, float]:
                lower_border, upper_border = self.valid_ranges[key][:2]
                assert lower_border <= value <= upper_border, f'Value for {key} is not within valid ranges!'
                
                
    def fill_user_input_with_defaults_where_needed(self, user_input: Dict[str, Any]) -> Dict[str, Any]:
        for key, default_value in self.values.items():
            if key not in user_input.keys():
                user_input[key] = default_value
        return user_input
        
        
    def _assert_valid_input(self,
                            default_values: Dict[str, Any],
                            valid_types: Dict[str, List[type]],
                            valid_value_ranges: Optional[Dict[str, Tuple]],
                            valid_value_options: Optional[Dict[str, Tuple]]
                           ) -> None:
        assert type(default_values) == dict, '"default_values" has to be a dictionary!'
        assert type(valid_types) == dict, '"valid_types" has to be a dictionary!'
        # Ensure default_values and valid_types have the same keys, 
        # that they are of type string, and that the type of the given 
        # default value actually matches the respective types specified in valid_types
        assert len(default_values.keys()) == len(valid_types.keys()), 'Different number of keys in "default_values" and "valid_types"!'
        for key, value in default_values.items():
            assert type(key) == str, 'All keys must be of type string!'
            assert key in valid_types.keys(), 'The keys of the "default_values" and "valid_types" dictionaries must be identical!'
            assert type(value) in valid_types[key], 'All default value types must be defined in the corresponding list of valid types!'
        # Finally, confirm that ranges are provided for numerical configs,
        # and that options are defined for string-based configs:
        for key, valid_value_types in valid_types.items():
            for valid_type in valid_value_types:
                if valid_type in [float, int]:
                    assert type(valid_value_ranges) == dict, '"valid_value_ranges" has to be a dictionary (or None)!'
                    assert_message = ('If "valid_types" includes "float" or "int", you also have to '
                                      'specify a tuple that denotes the valid range of values in this '
                                      'format: (start_idx, end_idx). Optionally, you can also add an '
                                      ' increment step size like: (start_idx, end_idx, step_size). For '
                                      f'the key "{key}", however, you did not provide such a range!')
                    assert type(valid_value_ranges[key]) == tuple, assert_message
                else:
                    continue

# %% ../nbs/00_configs.ipynb 8
class GUIConfigs:
    
    @property
    def layout(self) -> Dict:
        return {'width': '100%'}
    
    @property
    def style(self) -> Dict:
        return {'description_width': 'initial'}
    
    @property
    def widget_constructors(self) -> Dict[str, Callable]:
        widget_constructors = {'Checkbox': self._construct_a_checkbox,
                               'IntSlider': self._construct_an_intslider,
                               'FloatSlider': self._construct_a_floatslider,
                               'Dropdown': self._construct_a_dropdown,
                               'FileChooser': self._construct_a_filechooser,
                               'BoundedIntText': self._construct_a_boundedinttext,
                               'BoundedFloatText': self._construct_a_boundedfloattext}
        return widget_constructors
    
    
    def __init__(self,
                 widget_names: Dict[str, str],
                 descriptions: Dict[str, str],
                 tooltips: Optional[Dict[str, str]]=None
                ) -> None:
        self._assert_valid_inputs(widget_names, descriptions, tooltips)
        self.widget_names = widget_names
        self.descriptions = descriptions
        if tooltips == None:
            self.tooltips = {}
        else:
            self.tooltips = tooltips
    
    
    def _assert_valid_inputs(self,
                             widget_names: Dict[str, str],
                             descriptions: Dict[str, str],
                             tooltips: Optional[Dict[str, str]]
                            ) -> None:
        assert type(widget_names) == dict, '"widget_names" has to be a dictionary!'
        assert type(descriptions) == dict, '"descriptions" has to be a dictionary!'
        assert len(widget_names.keys()) == len(descriptions.keys()), 'The keys of "widget_names" and "descriptions" must be identical!'
        for key, name_value in widget_names.items():
            assert key in descriptions.keys(), 'The keys of "widget_names" and "descriptions" must be identical!'
            assert type(key) == str, 'All keys of "widget_names" and "descriptions" must be strings!'
            assert name_value in self.widget_constructors.keys(), f'The values in "widget_names" must be one of: {self.widget_constructors.keys()}'
            assert type(descriptions[key]) == str, 'The values in "descriptions" must be strings!'
        if tooltips != None:
            assert type(tooltips) == dict, '"tooltips" has to be a dictionary!'
            for key, tooltip_text in tooltips.items():
                assert key in widget_names.keys(), 'The keys of "tooltips" have to match with those in "widget_names" and "descriptions"!'
                assert type(tooltip_text) == str, 'The values in "tooltips" have to be strings!'
    
    
    def export_current_config_values(self) -> Dict:
        current_configs = {}
        for config_key in self.widget_names.keys():
            hbox_containing_config_widget = getattr(self, config_key)
            current_configs[config_key] = hbox_containing_config_widget.children[0].value
        return current_configs
    
            
    def construct_widget(self,
                         strategy_description: str,
                         default_configs: DefaultConfigs
                        ) -> None:
        self._assert_matching_keys_with_default_configs(default_configs = default_configs)
        self._initialize_individual_widgets_as_attributes(strategy_description = strategy_description, default_configs = default_configs)
        self.strategy_widget = self._combine_individual_widgets_in_vbox()
    
    
    def _assert_matching_keys_with_default_configs(self, default_configs: DefaultConfigs) -> None:
        assert_message = 'The keys of DefaultConfigs.values & GUIConfigs.widget_names must be identical!' 
        assert len(default_configs.values.keys()) == len(self.widget_names.keys()), assert_message
        for key in self.widget_names.keys():
            assert key in default_configs.values.keys(), assert_message
            
    
    def _initialize_individual_widgets_as_attributes(self, strategy_description: str, default_configs: DefaultConfigs) -> None:
        self.strategy_description_label = w.HTML(value = strategy_description)
        for config_key, widget_name in self.widget_names.items():
            widget_constructor = self.widget_constructors[widget_name] # creates the widget and embeds it in an HBox to avoids visualization bugs
            hbox_containing_config_widget = widget_constructor(key = config_key, default_configs = default_configs)
            hbox_containing_config_widget.layout = self.layout
            hbox_containing_config_widget.style = self.style
            setattr(self, config_key, hbox_containing_config_widget)


    def _construct_a_checkbox(self, key: str, default_configs: DefaultConfigs) -> WidgetType:
        checkbox = w.Checkbox(description = self.descriptions[key],
                              value = default_configs.values[key],
                              layout = self.layout,
                              style = self.style)
        return w.HBox([checkbox])
        
    
    def _construct_an_intslider(self, key: str, default_configs: DefaultConfigs) -> WidgetType:
        step_size = default_configs.get_step_size_if_present(key = key)
        tooltip = self._get_tooltip_if_present(key = key)
        intslider = w.IntSlider(description = self.descriptions[key],
                                value = default_configs.values[key],
                                min = default_configs.valid_ranges[key][0],
                                max = default_configs.valid_ranges[key][1],
                                step = step_size,
                                tooltip = tooltip,
                                layout = self.layout,
                                style = self.style)
        return w.HBox([intslider])
    
    
    def _construct_a_floatslider(self, key: str, default_configs: DefaultConfigs) -> WidgetType:
        step_size = default_configs.get_step_size_if_present(key = key)
        tooltip = self._get_tooltip_if_present(key = key)
        floatslider = w.FloatSlider(description = self.descriptions[key],
                                    value = default_configs.values[key],
                                    min = default_configs.valid_ranges[key][0],
                                    max = default_configs.valid_ranges[key][1],
                                    step = step_size,
                                    tooltip = tooltip,
                                    layout = self.layout,
                                    style = self.style)
        return w.HBox([floatslider])
    
    
    def _construct_a_dropdown(self, key: str, default_configs: DefaultConfigs) -> WidgetType:
        options = default_configs.get_options_if_present(key = key)
        if options == None:
            raise ValueError(f'No options available for {key} - please ensure that '
                             'you list all valid options in the "valid_value_options" '
                             'attribute of the DefaultConfigs!')
        dropdown = w.Dropdown(description = self.descriptions[key],
                              value = default_configs.values[key],
                              options = options,
                              layout = self.layout,
                              style = self.style)
        return w.HBox([dropdown])
    
    
    def _construct_a_filechooser(self, key: str, default_configs: DefaultConfigs) -> WidgetType:
        file_chooser = FileChooser(title = self.descriptions[key],
                                   path = default_configs.values[key],
                                   layout = self.layout)
        return w.HBox([file_chooser])


    def _get_tooltip_if_present(self, key: str) -> Optional[str]:
        if key in self.tooltips.keys():
            tooltip = self.tooltips[key]
        else:
            tooltip = None
        return tooltip
    
    
    def _construct_a_boundedinttext(self, key: str, default_configs: DefaultConfigs) -> WidgetType:
        step_size = default_configs.get_step_size_if_present(key = key)
        tooltip = self._get_tooltip_if_present(key = key)
        bounded_int_text = w.BoundedIntText(description = self.descriptions[key],
                                            value = default_configs.values[key],
                                            min = default_configs.valid_ranges[key][0],
                                            max = default_configs.valid_ranges[key][1],
                                            step = step_size,
                                            tooltip = tooltip,
                                            layout = self.layout,
                                            style = self.style)
        return w.HBox([bounded_int_text])


    def _construct_a_boundedfloattext(self, key: str, default_configs: DefaultConfigs) -> WidgetType:
        step_size = default_configs.get_step_size_if_present(key = key)
        tooltip = self._get_tooltip_if_present(key = key)
        bounded_float_text = w.BoundedFloatText(description = self.descriptions[key],
                                                value = default_configs.values[key],
                                                min = default_configs.valid_ranges[key][0],
                                                max = default_configs.valid_ranges[key][1],
                                                step = step_size,
                                                tooltip = tooltip,
                                                layout = self.layout,
                                                style = self.style)
        return w.HBox([bounded_float_text]) 


    def _combine_individual_widgets_in_vbox(self) -> WidgetType:
        all_widgets = [self.strategy_description_label]
        for config_key in self.widget_names.keys():
            all_widgets.append(getattr(self, config_key))
        return w.VBox(all_widgets)
