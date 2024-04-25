# ArkHelperCLI
An Arknights helper based on [MAA Core](https://github.com/MaaAssistantArknights/MaaAssistantArknights)，easily run MAA tasks in batches.

## deploy/dev
1. ``` git clone https://github.com/ArkHelper/ArkHelperCLI ```  
1. ``` cd ArkHelperCLI ``` 
1. Create folder ``` Data/Config ``` 
1. Create configs (details below)
1. Install requirements via pip
1. ``` python main.py ```

## config
ArkHelperCLI config is divided into three parts: [template_xxxxxx.yaml](./Docs/examples/template_default.yaml), [global.yaml](./Docs/examples/global.yaml), [personal.yaml](./Docs/examples/personal.yaml).  
Each task configuration configured in `personal.yaml` will be automatically generated from the template. Must create template_default.