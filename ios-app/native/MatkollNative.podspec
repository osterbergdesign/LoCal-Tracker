Pod::Spec.new do |s|
  s.name = 'MatkollNative'
  s.version = '1.0.0'
  s.summary = 'Native barcode scanner and Apple Health sync for the Matkoll iPhone app'
  s.license = 'MIT'
  s.homepage = 'https://github.com/osterbergdesign/LoCal-Tracker'
  s.author = 'osterbergdesign'
  s.source = { :git => 'https://github.com/osterbergdesign/LoCal-Tracker.git', :tag => s.version.to_s }
  s.source_files = 'ios/Sources/**/*.swift'
  s.ios.deployment_target = '15.0'
  s.dependency 'Capacitor'
  s.swift_version = '5.9'
  s.frameworks = 'AVFoundation', 'HealthKit'
end
