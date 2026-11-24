import 'package:flutter/material.dart';

import '../../../../data/services/digitizer_api_service.dart';
import '../view_models/studio_view_model.dart';

class ServerSettingsSheet extends StatefulWidget {
  const ServerSettingsSheet({super.key, required this.viewModel});

  final StudioViewModel viewModel;

  @override
  State<ServerSettingsSheet> createState() => _ServerSettingsSheetState();
}

class _ServerSettingsSheetState extends State<ServerSettingsSheet> {
  late final TextEditingController _urlController;
  late final TextEditingController _userController;
  late final TextEditingController _passController;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _urlController = TextEditingController(text: widget.viewModel.baseUrl);
    _userController =
        TextEditingController(text: widget.viewModel.username ?? '');
    _passController = TextEditingController();
  }

  @override
  void dispose() {
    _urlController.dispose();
    _userController.dispose();
    _passController.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    try {
      await widget.viewModel.updateServerSettings(
        baseUrl: _urlController.text,
        username: _userController.text,
        password: _passController.text,
      );
      if (mounted) {
        Navigator.of(context).pop();
      }
    } finally {
      if (mounted) {
        setState(() => _saving = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final caps = widget.viewModel.capabilities;
    return Padding(
      padding: EdgeInsets.only(
        left: 20,
        right: 20,
        top: 20,
        bottom: MediaQuery.viewInsetsOf(context).bottom + 24,
      ),
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const Icon(Icons.dns_rounded),
                const SizedBox(width: 8),
                Text(
                  'Telugu Digitizer Server',
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        fontWeight: FontWeight.w700,
                      ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            const Text(
              'Connects to https://lahari.org/telugu by default, or point to your local Raspberry Pi / desktop server.',
              style: TextStyle(fontSize: 13),
            ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                ActionChip(
                  label: const Text('lahari.org/telugu'),
                  onPressed: () => _urlController.text =
                      DigitizerApiService.defaultBaseUrl,
                ),
                ActionChip(
                  label: const Text('Pi LAN (192.168.1.13:8085)'),
                  onPressed: () =>
                      _urlController.text = 'http://192.168.1.13:8085',
                ),
                ActionChip(
                  label: const Text('Localhost (127.0.0.1:8000)'),
                  onPressed: () =>
                      _urlController.text = 'http://127.0.0.1:8000',
                ),
              ],
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _urlController,
              decoration: const InputDecoration(
                labelText: 'Server Base URL',
                hintText: 'https://lahari.org/telugu',
              ),
              keyboardType: TextInputType.url,
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _userController,
                    decoration: const InputDecoration(
                      labelText: 'Basic Auth User (optional)',
                    ),
                  ),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: TextField(
                    controller: _passController,
                    obscureText: true,
                    decoration: const InputDecoration(
                      labelText: 'Password (optional)',
                    ),
                  ),
                ),
              ],
            ),
            if (caps != null) ...[
              const SizedBox(height: 12),
              Text(
                'Host: ${caps.platformMachine} · Max upload: ${caps.maxUploadMb} MB · Max pages: ${caps.maxPdfPages}',
                style: const TextStyle(fontSize: 12),
              ),
            ],
            const SizedBox(height: 16),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                TextButton(
                  onPressed: _saving ? null : () => Navigator.of(context).pop(),
                  child: const Text('Cancel'),
                ),
                const SizedBox(width: 8),
                FilledButton.icon(
                  onPressed: _saving ? null : _save,
                  icon: const Icon(Icons.check),
                  label: Text(_saving ? 'Connecting...' : 'Save & Connect'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
