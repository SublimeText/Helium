Hermes package for Sublime Text 3
===

Hermes is a package for Sublime Text 3, which provides in-editor code execution and autocomplete in interaction with Jupyter kernels.
The concept of an editor extension communicating Jupyter kernels is inspired by @nteract's splendid Atom package [Hydrogen](https://github.com/nteract/Hydrogen). I want something like it in Sublime Text 3, too.

Any feedback is highly welcome. I hope this package will help your life with ST3!

![Introduction image](raw/images/README/intro.png)

Features
---------------

Currently it supports the actions below:

  - Connect to Jupyter gateway and start / interrupt / shutdown / restart kernels.
  - Connect to running Jupyter processes through HTTP.

    + The plugin can deal authorization by token.

  - Execute code block in view and get the result within ST3.

    + The executed code blocks are:

      * If there are selected regions, execute them.
      * If not, the adjacent lines with no empty line and not less indented than the line which includes the cursor are considered as the code block.

    + A view to store inputs and results is created for each kernel.
    + Figures with "image/png" type and passed as a "display_data" message can be shown within result view.

  - Autocomplete is provided by the kernel.
  - Get object inspection from the kernel.


Why using Jupyter?
-----------------

We can execute code, retrieve results including images, get completions and object inspections by the Jupyter protocol regardless of the interpreter implementation of languages if it has Jupyter kernel.
If we try to do that by directly running interpreters there should be several interpreter-specific problems, but we can entrust the kernel maintainers on language-specific problems by using Jupyter. 


Why not using Jupyter Notebook?
-----------------

I admit Jupyter Notebook is a powerful tool for instantly sharing small analysis work, exploring data or APIs, or making executable tutorials. Yes, I often use it, too.
However, in my opinion, it is not suited for projects with large code bases.
I want to jumpt across files instantly, make modules organized (not saved as `.ipynb`s), kick scripts with various parameters, and make project code more reusable and reproducible... but still I want to edit them with interactive feedback.


Installation
-----------------

Now this package is under the package control channel!

You can install it with Package Control plugin, run `Package Control: Install Package`, then choose `Hermes` from the package list.


Usage
-----------------

  0. (Outside of the editor) Start Jupyter notebook or create tunneling.
  1. Set url by `Hermes: Set URL` command (whose command name is `hermes_set_url`).
  2. Connect to kernel.

    - If no kernel is running, start a kernel by `Hermes: Start Kernel` (whose command name is `hermes_start_kernel`)
    - If kernel exists, correspond the view to the kernel by `Hermes: Connect Kernel` (whose command name is `hermes_connect_kernel`)

  3. Play with Jupyter kernels.

    - Execute code by `Hermes: Execute Block` (whose command name is `hermes_execute_block`).
    - Get Object Inspection by `Hermes: Get Object Inspection` (whose command name is `hermes_get_object_inspection`).
    - You should be able to get autocomplete from the kernel from the time you connected. If you don't want autocomplete, set `"complete"` as `false` in setting file.


TODOs
-----------------

  - [ ] Moving cursor on execution.
  - [ ] Rearrange log messages. Make option to set logging level.
  - [ ] Enable object inspection to be shown in popup.
  - [ ] Implement output as inline Phantom like LightTable or Hydrogen.
  - [ ] Password authentication.

