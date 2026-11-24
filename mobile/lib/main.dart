import 'package:flutter/material.dart';

import 'data/repositories/digitizer_repository.dart';
import 'data/services/digitizer_api_service.dart';
import 'ui/core/app_theme.dart';
import 'ui/features/studio/view_models/studio_view_model.dart';
import 'ui/features/studio/views/studio_home_view.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  final apiService = DigitizerApiService();
  final repository = DigitizerRepository(apiService: apiService);
  final viewModel = StudioViewModel(repository: repository)..initialize();
  runApp(TeluguDigitizerMobileApp(viewModel: viewModel));
}

class TeluguDigitizerMobileApp extends StatelessWidget {
  const TeluguDigitizerMobileApp({super.key, required this.viewModel});

  final StudioViewModel viewModel;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Telugu Book Digitizer',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.lightTheme(),
      home: StudioHomeView(viewModel: viewModel),
    );
  }
}
