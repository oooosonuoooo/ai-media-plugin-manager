# Configuration checkpoints and recovery

Before adding or changing editor resources, run `python3 scripts/create_checkpoint.py`. It saves the active Krita and Kdenlive user settings and resource profiles under the XDG data directory, verifies SHA-256 hashes against the source files, and prints the local checkpoint path.

The checkpoint is machine-specific and may contain paths, preferences, and user resources. Keep it local; never add it to this repository or publish it.

To recover:

1. Close Krita and Kdenlive.
2. Choose only the configuration file or resource folder that needs recovery.
3. Copy the current version aside before restoring the checkpoint copy.
4. Restore the selected file/folder, then launch the editor and check that the project/profile loads.
5. Avoid replacing an entire resource profile if only one bundle or setting needs recovery; preserve changes made since the checkpoint.

The manager does not restore editor profiles automatically. This keeps recovery selective and avoids discarding newer user changes.
