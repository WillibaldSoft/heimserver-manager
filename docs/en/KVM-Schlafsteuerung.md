# Sleep Control per VM

Under KVM management, sleep control can be selected and saved directly in each table row and on the VM detail page. Settings are stored using the VM UUID in `kvm_sleep_policy`; new and existing VMs initially use "Keep Server Awake".

- **Keep Server Awake:** active and paused VMs report a blocker.
- **Shutdown via Sleep & Wake:** active VMs remain blocked until they are shut down. For an active suspend, hibernate, or off schedule with automation enabled and actual execution, regular shutdown requests are issued after the keep-awake period. Other blockers prevent this step. The host state is only changed after a renewed central blocker check.
- **Do Not Report Blocker:** this VM does not keep the host awake and receives no shutdown request from the KVM module. Thus, the host can sleep or shut down with an active VM.

The keep-awake period is not constantly extended by managed VMs. KVM background jobs remain locked; at most one new shutdown request is started per scheduler cycle. Retries for the same VM occur no sooner than five minutes later. Errors are visible under KVM → Jobs. A non-responsive guest remains a blocker. Paused VMs must first be resumed manually. There is no automatic hard power-off.

The mode is rechecked before executing an queued shutdown job. Switching back does not prevent pending requests; a request already sent to the guest cannot be withdrawn.

Separate libvirt autostart still applies for host restarts. There is no automatic restart of shut-down VMs after host suspend. Manual host actions are not converted into VM schedule actions by this extension.

Tests simulate VMs and host actions; production VMs are not shut down for testing purposes.
