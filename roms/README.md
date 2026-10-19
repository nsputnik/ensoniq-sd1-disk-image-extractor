# ROMs (you supply these)

Put MAME's ROM sets for the Ensoniq SD-1 (32 voice) here, or point `SD1_ROMPATH` at the folder that holds them:

- `sd132.zip`: the SD-1/32 firmware and wave ROMs (MAME driver `sd132`)
- `esq2x40_vfx.zip`: the front-panel display font

They're Ensoniq's copyright and aren't included. `tools/setup.py` checks them with `mame -verifyroms sd132`.
