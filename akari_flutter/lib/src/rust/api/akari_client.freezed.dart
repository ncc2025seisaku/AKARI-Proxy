// GENERATED CODE - DO NOT MODIFY BY HAND
// coverage:ignore-file
// ignore_for_file: type=lint
// ignore_for_file: unused_element, deprecated_member_use, deprecated_member_use_from_same_package, use_function_type_syntax_for_parameters, unnecessary_const, avoid_init_to_null, invalid_override_different_default_values_named, prefer_expression_function_bodies, annotate_overrides, invalid_annotation_target, unnecessary_question_mark

part of 'akari_client.dart';

// **************************************************************************
// FreezedGenerator
// **************************************************************************

// dart format off
T _$identity<T>(T value) => value;
/// @nodoc
mixin _$AkariHttpResponse {

 int get statusCode; List<(String, String)> get headers; Uint8List get body; AkariTransferStats get stats;
/// Create a copy of AkariHttpResponse
/// with the given fields replaced by the non-null parameter values.
@JsonKey(includeFromJson: false, includeToJson: false)
@pragma('vm:prefer-inline')
$AkariHttpResponseCopyWith<AkariHttpResponse> get copyWith => _$AkariHttpResponseCopyWithImpl<AkariHttpResponse>(this as AkariHttpResponse, _$identity);



@override
bool operator ==(Object other) {
  return identical(this, other) || (other.runtimeType == runtimeType&&other is AkariHttpResponse&&(identical(other.statusCode, statusCode) || other.statusCode == statusCode)&&const DeepCollectionEquality().equals(other.headers, headers)&&const DeepCollectionEquality().equals(other.body, body)&&(identical(other.stats, stats) || other.stats == stats));
}


@override
int get hashCode => Object.hash(runtimeType,statusCode,const DeepCollectionEquality().hash(headers),const DeepCollectionEquality().hash(body),stats);

@override
String toString() {
  return 'AkariHttpResponse(statusCode: $statusCode, headers: $headers, body: $body, stats: $stats)';
}


}

/// @nodoc
abstract mixin class $AkariHttpResponseCopyWith<$Res>  {
  factory $AkariHttpResponseCopyWith(AkariHttpResponse value, $Res Function(AkariHttpResponse) _then) = _$AkariHttpResponseCopyWithImpl;
@useResult
$Res call({
 int statusCode, List<(String, String)> headers, Uint8List body, AkariTransferStats stats
});


$AkariTransferStatsCopyWith<$Res> get stats;

}
/// @nodoc
class _$AkariHttpResponseCopyWithImpl<$Res>
    implements $AkariHttpResponseCopyWith<$Res> {
  _$AkariHttpResponseCopyWithImpl(this._self, this._then);

  final AkariHttpResponse _self;
  final $Res Function(AkariHttpResponse) _then;

/// Create a copy of AkariHttpResponse
/// with the given fields replaced by the non-null parameter values.
@pragma('vm:prefer-inline') @override $Res call({Object? statusCode = null,Object? headers = null,Object? body = null,Object? stats = null,}) {
  return _then(_self.copyWith(
statusCode: null == statusCode ? _self.statusCode : statusCode // ignore: cast_nullable_to_non_nullable
as int,headers: null == headers ? _self.headers : headers // ignore: cast_nullable_to_non_nullable
as List<(String, String)>,body: null == body ? _self.body : body // ignore: cast_nullable_to_non_nullable
as Uint8List,stats: null == stats ? _self.stats : stats // ignore: cast_nullable_to_non_nullable
as AkariTransferStats,
  ));
}
/// Create a copy of AkariHttpResponse
/// with the given fields replaced by the non-null parameter values.
@override
@pragma('vm:prefer-inline')
$AkariTransferStatsCopyWith<$Res> get stats {
  
  return $AkariTransferStatsCopyWith<$Res>(_self.stats, (value) {
    return _then(_self.copyWith(stats: value));
  });
}
}


/// Adds pattern-matching-related methods to [AkariHttpResponse].
extension AkariHttpResponsePatterns on AkariHttpResponse {
/// A variant of `map` that fallback to returning `orElse`.
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case final Subclass value:
///     return ...;
///   case _:
///     return orElse();
/// }
/// ```

@optionalTypeArgs TResult maybeMap<TResult extends Object?>(TResult Function( _AkariHttpResponse value)?  $default,{required TResult orElse(),}){
final _that = this;
switch (_that) {
case _AkariHttpResponse() when $default != null:
return $default(_that);case _:
  return orElse();

}
}
/// A `switch`-like method, using callbacks.
///
/// Callbacks receives the raw object, upcasted.
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case final Subclass value:
///     return ...;
///   case final Subclass2 value:
///     return ...;
/// }
/// ```

@optionalTypeArgs TResult map<TResult extends Object?>(TResult Function( _AkariHttpResponse value)  $default,){
final _that = this;
switch (_that) {
case _AkariHttpResponse():
return $default(_that);}
}
/// A variant of `map` that fallback to returning `null`.
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case final Subclass value:
///     return ...;
///   case _:
///     return null;
/// }
/// ```

@optionalTypeArgs TResult? mapOrNull<TResult extends Object?>(TResult? Function( _AkariHttpResponse value)?  $default,){
final _that = this;
switch (_that) {
case _AkariHttpResponse() when $default != null:
return $default(_that);case _:
  return null;

}
}
/// A variant of `when` that fallback to an `orElse` callback.
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case Subclass(:final field):
///     return ...;
///   case _:
///     return orElse();
/// }
/// ```

@optionalTypeArgs TResult maybeWhen<TResult extends Object?>(TResult Function( int statusCode,  List<(String, String)> headers,  Uint8List body,  AkariTransferStats stats)?  $default,{required TResult orElse(),}) {final _that = this;
switch (_that) {
case _AkariHttpResponse() when $default != null:
return $default(_that.statusCode,_that.headers,_that.body,_that.stats);case _:
  return orElse();

}
}
/// A `switch`-like method, using callbacks.
///
/// As opposed to `map`, this offers destructuring.
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case Subclass(:final field):
///     return ...;
///   case Subclass2(:final field2):
///     return ...;
/// }
/// ```

@optionalTypeArgs TResult when<TResult extends Object?>(TResult Function( int statusCode,  List<(String, String)> headers,  Uint8List body,  AkariTransferStats stats)  $default,) {final _that = this;
switch (_that) {
case _AkariHttpResponse():
return $default(_that.statusCode,_that.headers,_that.body,_that.stats);}
}
/// A variant of `when` that fallback to returning `null`
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case Subclass(:final field):
///     return ...;
///   case _:
///     return null;
/// }
/// ```

@optionalTypeArgs TResult? whenOrNull<TResult extends Object?>(TResult? Function( int statusCode,  List<(String, String)> headers,  Uint8List body,  AkariTransferStats stats)?  $default,) {final _that = this;
switch (_that) {
case _AkariHttpResponse() when $default != null:
return $default(_that.statusCode,_that.headers,_that.body,_that.stats);case _:
  return null;

}
}

}

/// @nodoc


class _AkariHttpResponse implements AkariHttpResponse {
  const _AkariHttpResponse({required this.statusCode, required final  List<(String, String)> headers, required this.body, required this.stats}): _headers = headers;
  

@override final  int statusCode;
 final  List<(String, String)> _headers;
@override List<(String, String)> get headers {
  if (_headers is EqualUnmodifiableListView) return _headers;
  // ignore: implicit_dynamic_type
  return EqualUnmodifiableListView(_headers);
}

@override final  Uint8List body;
@override final  AkariTransferStats stats;

/// Create a copy of AkariHttpResponse
/// with the given fields replaced by the non-null parameter values.
@override @JsonKey(includeFromJson: false, includeToJson: false)
@pragma('vm:prefer-inline')
_$AkariHttpResponseCopyWith<_AkariHttpResponse> get copyWith => __$AkariHttpResponseCopyWithImpl<_AkariHttpResponse>(this, _$identity);



@override
bool operator ==(Object other) {
  return identical(this, other) || (other.runtimeType == runtimeType&&other is _AkariHttpResponse&&(identical(other.statusCode, statusCode) || other.statusCode == statusCode)&&const DeepCollectionEquality().equals(other._headers, _headers)&&const DeepCollectionEquality().equals(other.body, body)&&(identical(other.stats, stats) || other.stats == stats));
}


@override
int get hashCode => Object.hash(runtimeType,statusCode,const DeepCollectionEquality().hash(_headers),const DeepCollectionEquality().hash(body),stats);

@override
String toString() {
  return 'AkariHttpResponse(statusCode: $statusCode, headers: $headers, body: $body, stats: $stats)';
}


}

/// @nodoc
abstract mixin class _$AkariHttpResponseCopyWith<$Res> implements $AkariHttpResponseCopyWith<$Res> {
  factory _$AkariHttpResponseCopyWith(_AkariHttpResponse value, $Res Function(_AkariHttpResponse) _then) = __$AkariHttpResponseCopyWithImpl;
@override @useResult
$Res call({
 int statusCode, List<(String, String)> headers, Uint8List body, AkariTransferStats stats
});


@override $AkariTransferStatsCopyWith<$Res> get stats;

}
/// @nodoc
class __$AkariHttpResponseCopyWithImpl<$Res>
    implements _$AkariHttpResponseCopyWith<$Res> {
  __$AkariHttpResponseCopyWithImpl(this._self, this._then);

  final _AkariHttpResponse _self;
  final $Res Function(_AkariHttpResponse) _then;

/// Create a copy of AkariHttpResponse
/// with the given fields replaced by the non-null parameter values.
@override @pragma('vm:prefer-inline') $Res call({Object? statusCode = null,Object? headers = null,Object? body = null,Object? stats = null,}) {
  return _then(_AkariHttpResponse(
statusCode: null == statusCode ? _self.statusCode : statusCode // ignore: cast_nullable_to_non_nullable
as int,headers: null == headers ? _self._headers : headers // ignore: cast_nullable_to_non_nullable
as List<(String, String)>,body: null == body ? _self.body : body // ignore: cast_nullable_to_non_nullable
as Uint8List,stats: null == stats ? _self.stats : stats // ignore: cast_nullable_to_non_nullable
as AkariTransferStats,
  ));
}

/// Create a copy of AkariHttpResponse
/// with the given fields replaced by the non-null parameter values.
@override
@pragma('vm:prefer-inline')
$AkariTransferStatsCopyWith<$Res> get stats {
  
  return $AkariTransferStatsCopyWith<$Res>(_self.stats, (value) {
    return _then(_self.copyWith(stats: value));
  });
}
}

/// @nodoc
mixin _$AkariRequestConfig {

 BigInt get timeoutMs; int? get maxNackRounds; int get initialRequestRetries; BigInt get sockTimeoutMs; BigInt get firstSeqTimeoutMs; bool get aggTag; bool get shortId;
/// Create a copy of AkariRequestConfig
/// with the given fields replaced by the non-null parameter values.
@JsonKey(includeFromJson: false, includeToJson: false)
@pragma('vm:prefer-inline')
$AkariRequestConfigCopyWith<AkariRequestConfig> get copyWith => _$AkariRequestConfigCopyWithImpl<AkariRequestConfig>(this as AkariRequestConfig, _$identity);



@override
bool operator ==(Object other) {
  return identical(this, other) || (other.runtimeType == runtimeType&&other is AkariRequestConfig&&(identical(other.timeoutMs, timeoutMs) || other.timeoutMs == timeoutMs)&&(identical(other.maxNackRounds, maxNackRounds) || other.maxNackRounds == maxNackRounds)&&(identical(other.initialRequestRetries, initialRequestRetries) || other.initialRequestRetries == initialRequestRetries)&&(identical(other.sockTimeoutMs, sockTimeoutMs) || other.sockTimeoutMs == sockTimeoutMs)&&(identical(other.firstSeqTimeoutMs, firstSeqTimeoutMs) || other.firstSeqTimeoutMs == firstSeqTimeoutMs)&&(identical(other.aggTag, aggTag) || other.aggTag == aggTag)&&(identical(other.shortId, shortId) || other.shortId == shortId));
}


@override
int get hashCode => Object.hash(runtimeType,timeoutMs,maxNackRounds,initialRequestRetries,sockTimeoutMs,firstSeqTimeoutMs,aggTag,shortId);

@override
String toString() {
  return 'AkariRequestConfig(timeoutMs: $timeoutMs, maxNackRounds: $maxNackRounds, initialRequestRetries: $initialRequestRetries, sockTimeoutMs: $sockTimeoutMs, firstSeqTimeoutMs: $firstSeqTimeoutMs, aggTag: $aggTag, shortId: $shortId)';
}


}

/// @nodoc
abstract mixin class $AkariRequestConfigCopyWith<$Res>  {
  factory $AkariRequestConfigCopyWith(AkariRequestConfig value, $Res Function(AkariRequestConfig) _then) = _$AkariRequestConfigCopyWithImpl;
@useResult
$Res call({
 BigInt timeoutMs, int? maxNackRounds, int initialRequestRetries, BigInt sockTimeoutMs, BigInt firstSeqTimeoutMs, bool aggTag, bool shortId
});




}
/// @nodoc
class _$AkariRequestConfigCopyWithImpl<$Res>
    implements $AkariRequestConfigCopyWith<$Res> {
  _$AkariRequestConfigCopyWithImpl(this._self, this._then);

  final AkariRequestConfig _self;
  final $Res Function(AkariRequestConfig) _then;

/// Create a copy of AkariRequestConfig
/// with the given fields replaced by the non-null parameter values.
@pragma('vm:prefer-inline') @override $Res call({Object? timeoutMs = null,Object? maxNackRounds = freezed,Object? initialRequestRetries = null,Object? sockTimeoutMs = null,Object? firstSeqTimeoutMs = null,Object? aggTag = null,Object? shortId = null,}) {
  return _then(_self.copyWith(
timeoutMs: null == timeoutMs ? _self.timeoutMs : timeoutMs // ignore: cast_nullable_to_non_nullable
as BigInt,maxNackRounds: freezed == maxNackRounds ? _self.maxNackRounds : maxNackRounds // ignore: cast_nullable_to_non_nullable
as int?,initialRequestRetries: null == initialRequestRetries ? _self.initialRequestRetries : initialRequestRetries // ignore: cast_nullable_to_non_nullable
as int,sockTimeoutMs: null == sockTimeoutMs ? _self.sockTimeoutMs : sockTimeoutMs // ignore: cast_nullable_to_non_nullable
as BigInt,firstSeqTimeoutMs: null == firstSeqTimeoutMs ? _self.firstSeqTimeoutMs : firstSeqTimeoutMs // ignore: cast_nullable_to_non_nullable
as BigInt,aggTag: null == aggTag ? _self.aggTag : aggTag // ignore: cast_nullable_to_non_nullable
as bool,shortId: null == shortId ? _self.shortId : shortId // ignore: cast_nullable_to_non_nullable
as bool,
  ));
}

}


/// Adds pattern-matching-related methods to [AkariRequestConfig].
extension AkariRequestConfigPatterns on AkariRequestConfig {
/// A variant of `map` that fallback to returning `orElse`.
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case final Subclass value:
///     return ...;
///   case _:
///     return orElse();
/// }
/// ```

@optionalTypeArgs TResult maybeMap<TResult extends Object?>(TResult Function( _AkariRequestConfig value)?  $default,{required TResult orElse(),}){
final _that = this;
switch (_that) {
case _AkariRequestConfig() when $default != null:
return $default(_that);case _:
  return orElse();

}
}
/// A `switch`-like method, using callbacks.
///
/// Callbacks receives the raw object, upcasted.
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case final Subclass value:
///     return ...;
///   case final Subclass2 value:
///     return ...;
/// }
/// ```

@optionalTypeArgs TResult map<TResult extends Object?>(TResult Function( _AkariRequestConfig value)  $default,){
final _that = this;
switch (_that) {
case _AkariRequestConfig():
return $default(_that);}
}
/// A variant of `map` that fallback to returning `null`.
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case final Subclass value:
///     return ...;
///   case _:
///     return null;
/// }
/// ```

@optionalTypeArgs TResult? mapOrNull<TResult extends Object?>(TResult? Function( _AkariRequestConfig value)?  $default,){
final _that = this;
switch (_that) {
case _AkariRequestConfig() when $default != null:
return $default(_that);case _:
  return null;

}
}
/// A variant of `when` that fallback to an `orElse` callback.
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case Subclass(:final field):
///     return ...;
///   case _:
///     return orElse();
/// }
/// ```

@optionalTypeArgs TResult maybeWhen<TResult extends Object?>(TResult Function( BigInt timeoutMs,  int? maxNackRounds,  int initialRequestRetries,  BigInt sockTimeoutMs,  BigInt firstSeqTimeoutMs,  bool aggTag,  bool shortId)?  $default,{required TResult orElse(),}) {final _that = this;
switch (_that) {
case _AkariRequestConfig() when $default != null:
return $default(_that.timeoutMs,_that.maxNackRounds,_that.initialRequestRetries,_that.sockTimeoutMs,_that.firstSeqTimeoutMs,_that.aggTag,_that.shortId);case _:
  return orElse();

}
}
/// A `switch`-like method, using callbacks.
///
/// As opposed to `map`, this offers destructuring.
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case Subclass(:final field):
///     return ...;
///   case Subclass2(:final field2):
///     return ...;
/// }
/// ```

@optionalTypeArgs TResult when<TResult extends Object?>(TResult Function( BigInt timeoutMs,  int? maxNackRounds,  int initialRequestRetries,  BigInt sockTimeoutMs,  BigInt firstSeqTimeoutMs,  bool aggTag,  bool shortId)  $default,) {final _that = this;
switch (_that) {
case _AkariRequestConfig():
return $default(_that.timeoutMs,_that.maxNackRounds,_that.initialRequestRetries,_that.sockTimeoutMs,_that.firstSeqTimeoutMs,_that.aggTag,_that.shortId);}
}
/// A variant of `when` that fallback to returning `null`
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case Subclass(:final field):
///     return ...;
///   case _:
///     return null;
/// }
/// ```

@optionalTypeArgs TResult? whenOrNull<TResult extends Object?>(TResult? Function( BigInt timeoutMs,  int? maxNackRounds,  int initialRequestRetries,  BigInt sockTimeoutMs,  BigInt firstSeqTimeoutMs,  bool aggTag,  bool shortId)?  $default,) {final _that = this;
switch (_that) {
case _AkariRequestConfig() when $default != null:
return $default(_that.timeoutMs,_that.maxNackRounds,_that.initialRequestRetries,_that.sockTimeoutMs,_that.firstSeqTimeoutMs,_that.aggTag,_that.shortId);case _:
  return null;

}
}

}

/// @nodoc


class _AkariRequestConfig extends AkariRequestConfig {
  const _AkariRequestConfig({required this.timeoutMs, this.maxNackRounds, required this.initialRequestRetries, required this.sockTimeoutMs, required this.firstSeqTimeoutMs, required this.aggTag, required this.shortId}): super._();
  

@override final  BigInt timeoutMs;
@override final  int? maxNackRounds;
@override final  int initialRequestRetries;
@override final  BigInt sockTimeoutMs;
@override final  BigInt firstSeqTimeoutMs;
@override final  bool aggTag;
@override final  bool shortId;

/// Create a copy of AkariRequestConfig
/// with the given fields replaced by the non-null parameter values.
@override @JsonKey(includeFromJson: false, includeToJson: false)
@pragma('vm:prefer-inline')
_$AkariRequestConfigCopyWith<_AkariRequestConfig> get copyWith => __$AkariRequestConfigCopyWithImpl<_AkariRequestConfig>(this, _$identity);



@override
bool operator ==(Object other) {
  return identical(this, other) || (other.runtimeType == runtimeType&&other is _AkariRequestConfig&&(identical(other.timeoutMs, timeoutMs) || other.timeoutMs == timeoutMs)&&(identical(other.maxNackRounds, maxNackRounds) || other.maxNackRounds == maxNackRounds)&&(identical(other.initialRequestRetries, initialRequestRetries) || other.initialRequestRetries == initialRequestRetries)&&(identical(other.sockTimeoutMs, sockTimeoutMs) || other.sockTimeoutMs == sockTimeoutMs)&&(identical(other.firstSeqTimeoutMs, firstSeqTimeoutMs) || other.firstSeqTimeoutMs == firstSeqTimeoutMs)&&(identical(other.aggTag, aggTag) || other.aggTag == aggTag)&&(identical(other.shortId, shortId) || other.shortId == shortId));
}


@override
int get hashCode => Object.hash(runtimeType,timeoutMs,maxNackRounds,initialRequestRetries,sockTimeoutMs,firstSeqTimeoutMs,aggTag,shortId);

@override
String toString() {
  return 'AkariRequestConfig(timeoutMs: $timeoutMs, maxNackRounds: $maxNackRounds, initialRequestRetries: $initialRequestRetries, sockTimeoutMs: $sockTimeoutMs, firstSeqTimeoutMs: $firstSeqTimeoutMs, aggTag: $aggTag, shortId: $shortId)';
}


}

/// @nodoc
abstract mixin class _$AkariRequestConfigCopyWith<$Res> implements $AkariRequestConfigCopyWith<$Res> {
  factory _$AkariRequestConfigCopyWith(_AkariRequestConfig value, $Res Function(_AkariRequestConfig) _then) = __$AkariRequestConfigCopyWithImpl;
@override @useResult
$Res call({
 BigInt timeoutMs, int? maxNackRounds, int initialRequestRetries, BigInt sockTimeoutMs, BigInt firstSeqTimeoutMs, bool aggTag, bool shortId
});




}
/// @nodoc
class __$AkariRequestConfigCopyWithImpl<$Res>
    implements _$AkariRequestConfigCopyWith<$Res> {
  __$AkariRequestConfigCopyWithImpl(this._self, this._then);

  final _AkariRequestConfig _self;
  final $Res Function(_AkariRequestConfig) _then;

/// Create a copy of AkariRequestConfig
/// with the given fields replaced by the non-null parameter values.
@override @pragma('vm:prefer-inline') $Res call({Object? timeoutMs = null,Object? maxNackRounds = freezed,Object? initialRequestRetries = null,Object? sockTimeoutMs = null,Object? firstSeqTimeoutMs = null,Object? aggTag = null,Object? shortId = null,}) {
  return _then(_AkariRequestConfig(
timeoutMs: null == timeoutMs ? _self.timeoutMs : timeoutMs // ignore: cast_nullable_to_non_nullable
as BigInt,maxNackRounds: freezed == maxNackRounds ? _self.maxNackRounds : maxNackRounds // ignore: cast_nullable_to_non_nullable
as int?,initialRequestRetries: null == initialRequestRetries ? _self.initialRequestRetries : initialRequestRetries // ignore: cast_nullable_to_non_nullable
as int,sockTimeoutMs: null == sockTimeoutMs ? _self.sockTimeoutMs : sockTimeoutMs // ignore: cast_nullable_to_non_nullable
as BigInt,firstSeqTimeoutMs: null == firstSeqTimeoutMs ? _self.firstSeqTimeoutMs : firstSeqTimeoutMs // ignore: cast_nullable_to_non_nullable
as BigInt,aggTag: null == aggTag ? _self.aggTag : aggTag // ignore: cast_nullable_to_non_nullable
as bool,shortId: null == shortId ? _self.shortId : shortId // ignore: cast_nullable_to_non_nullable
as bool,
  ));
}


}

/// @nodoc
mixin _$AkariTransferStats {

 BigInt get bytesSent; BigInt get bytesReceived; int get nacksSent; int get requestRetries;
/// Create a copy of AkariTransferStats
/// with the given fields replaced by the non-null parameter values.
@JsonKey(includeFromJson: false, includeToJson: false)
@pragma('vm:prefer-inline')
$AkariTransferStatsCopyWith<AkariTransferStats> get copyWith => _$AkariTransferStatsCopyWithImpl<AkariTransferStats>(this as AkariTransferStats, _$identity);



@override
bool operator ==(Object other) {
  return identical(this, other) || (other.runtimeType == runtimeType&&other is AkariTransferStats&&(identical(other.bytesSent, bytesSent) || other.bytesSent == bytesSent)&&(identical(other.bytesReceived, bytesReceived) || other.bytesReceived == bytesReceived)&&(identical(other.nacksSent, nacksSent) || other.nacksSent == nacksSent)&&(identical(other.requestRetries, requestRetries) || other.requestRetries == requestRetries));
}


@override
int get hashCode => Object.hash(runtimeType,bytesSent,bytesReceived,nacksSent,requestRetries);

@override
String toString() {
  return 'AkariTransferStats(bytesSent: $bytesSent, bytesReceived: $bytesReceived, nacksSent: $nacksSent, requestRetries: $requestRetries)';
}


}

/// @nodoc
abstract mixin class $AkariTransferStatsCopyWith<$Res>  {
  factory $AkariTransferStatsCopyWith(AkariTransferStats value, $Res Function(AkariTransferStats) _then) = _$AkariTransferStatsCopyWithImpl;
@useResult
$Res call({
 BigInt bytesSent, BigInt bytesReceived, int nacksSent, int requestRetries
});




}
/// @nodoc
class _$AkariTransferStatsCopyWithImpl<$Res>
    implements $AkariTransferStatsCopyWith<$Res> {
  _$AkariTransferStatsCopyWithImpl(this._self, this._then);

  final AkariTransferStats _self;
  final $Res Function(AkariTransferStats) _then;

/// Create a copy of AkariTransferStats
/// with the given fields replaced by the non-null parameter values.
@pragma('vm:prefer-inline') @override $Res call({Object? bytesSent = null,Object? bytesReceived = null,Object? nacksSent = null,Object? requestRetries = null,}) {
  return _then(_self.copyWith(
bytesSent: null == bytesSent ? _self.bytesSent : bytesSent // ignore: cast_nullable_to_non_nullable
as BigInt,bytesReceived: null == bytesReceived ? _self.bytesReceived : bytesReceived // ignore: cast_nullable_to_non_nullable
as BigInt,nacksSent: null == nacksSent ? _self.nacksSent : nacksSent // ignore: cast_nullable_to_non_nullable
as int,requestRetries: null == requestRetries ? _self.requestRetries : requestRetries // ignore: cast_nullable_to_non_nullable
as int,
  ));
}

}


/// Adds pattern-matching-related methods to [AkariTransferStats].
extension AkariTransferStatsPatterns on AkariTransferStats {
/// A variant of `map` that fallback to returning `orElse`.
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case final Subclass value:
///     return ...;
///   case _:
///     return orElse();
/// }
/// ```

@optionalTypeArgs TResult maybeMap<TResult extends Object?>(TResult Function( _AkariTransferStats value)?  $default,{required TResult orElse(),}){
final _that = this;
switch (_that) {
case _AkariTransferStats() when $default != null:
return $default(_that);case _:
  return orElse();

}
}
/// A `switch`-like method, using callbacks.
///
/// Callbacks receives the raw object, upcasted.
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case final Subclass value:
///     return ...;
///   case final Subclass2 value:
///     return ...;
/// }
/// ```

@optionalTypeArgs TResult map<TResult extends Object?>(TResult Function( _AkariTransferStats value)  $default,){
final _that = this;
switch (_that) {
case _AkariTransferStats():
return $default(_that);}
}
/// A variant of `map` that fallback to returning `null`.
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case final Subclass value:
///     return ...;
///   case _:
///     return null;
/// }
/// ```

@optionalTypeArgs TResult? mapOrNull<TResult extends Object?>(TResult? Function( _AkariTransferStats value)?  $default,){
final _that = this;
switch (_that) {
case _AkariTransferStats() when $default != null:
return $default(_that);case _:
  return null;

}
}
/// A variant of `when` that fallback to an `orElse` callback.
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case Subclass(:final field):
///     return ...;
///   case _:
///     return orElse();
/// }
/// ```

@optionalTypeArgs TResult maybeWhen<TResult extends Object?>(TResult Function( BigInt bytesSent,  BigInt bytesReceived,  int nacksSent,  int requestRetries)?  $default,{required TResult orElse(),}) {final _that = this;
switch (_that) {
case _AkariTransferStats() when $default != null:
return $default(_that.bytesSent,_that.bytesReceived,_that.nacksSent,_that.requestRetries);case _:
  return orElse();

}
}
/// A `switch`-like method, using callbacks.
///
/// As opposed to `map`, this offers destructuring.
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case Subclass(:final field):
///     return ...;
///   case Subclass2(:final field2):
///     return ...;
/// }
/// ```

@optionalTypeArgs TResult when<TResult extends Object?>(TResult Function( BigInt bytesSent,  BigInt bytesReceived,  int nacksSent,  int requestRetries)  $default,) {final _that = this;
switch (_that) {
case _AkariTransferStats():
return $default(_that.bytesSent,_that.bytesReceived,_that.nacksSent,_that.requestRetries);}
}
/// A variant of `when` that fallback to returning `null`
///
/// It is equivalent to doing:
/// ```dart
/// switch (sealedClass) {
///   case Subclass(:final field):
///     return ...;
///   case _:
///     return null;
/// }
/// ```

@optionalTypeArgs TResult? whenOrNull<TResult extends Object?>(TResult? Function( BigInt bytesSent,  BigInt bytesReceived,  int nacksSent,  int requestRetries)?  $default,) {final _that = this;
switch (_that) {
case _AkariTransferStats() when $default != null:
return $default(_that.bytesSent,_that.bytesReceived,_that.nacksSent,_that.requestRetries);case _:
  return null;

}
}

}

/// @nodoc


class _AkariTransferStats implements AkariTransferStats {
  const _AkariTransferStats({required this.bytesSent, required this.bytesReceived, required this.nacksSent, required this.requestRetries});
  

@override final  BigInt bytesSent;
@override final  BigInt bytesReceived;
@override final  int nacksSent;
@override final  int requestRetries;

/// Create a copy of AkariTransferStats
/// with the given fields replaced by the non-null parameter values.
@override @JsonKey(includeFromJson: false, includeToJson: false)
@pragma('vm:prefer-inline')
_$AkariTransferStatsCopyWith<_AkariTransferStats> get copyWith => __$AkariTransferStatsCopyWithImpl<_AkariTransferStats>(this, _$identity);



@override
bool operator ==(Object other) {
  return identical(this, other) || (other.runtimeType == runtimeType&&other is _AkariTransferStats&&(identical(other.bytesSent, bytesSent) || other.bytesSent == bytesSent)&&(identical(other.bytesReceived, bytesReceived) || other.bytesReceived == bytesReceived)&&(identical(other.nacksSent, nacksSent) || other.nacksSent == nacksSent)&&(identical(other.requestRetries, requestRetries) || other.requestRetries == requestRetries));
}


@override
int get hashCode => Object.hash(runtimeType,bytesSent,bytesReceived,nacksSent,requestRetries);

@override
String toString() {
  return 'AkariTransferStats(bytesSent: $bytesSent, bytesReceived: $bytesReceived, nacksSent: $nacksSent, requestRetries: $requestRetries)';
}


}

/// @nodoc
abstract mixin class _$AkariTransferStatsCopyWith<$Res> implements $AkariTransferStatsCopyWith<$Res> {
  factory _$AkariTransferStatsCopyWith(_AkariTransferStats value, $Res Function(_AkariTransferStats) _then) = __$AkariTransferStatsCopyWithImpl;
@override @useResult
$Res call({
 BigInt bytesSent, BigInt bytesReceived, int nacksSent, int requestRetries
});




}
/// @nodoc
class __$AkariTransferStatsCopyWithImpl<$Res>
    implements _$AkariTransferStatsCopyWith<$Res> {
  __$AkariTransferStatsCopyWithImpl(this._self, this._then);

  final _AkariTransferStats _self;
  final $Res Function(_AkariTransferStats) _then;

/// Create a copy of AkariTransferStats
/// with the given fields replaced by the non-null parameter values.
@override @pragma('vm:prefer-inline') $Res call({Object? bytesSent = null,Object? bytesReceived = null,Object? nacksSent = null,Object? requestRetries = null,}) {
  return _then(_AkariTransferStats(
bytesSent: null == bytesSent ? _self.bytesSent : bytesSent // ignore: cast_nullable_to_non_nullable
as BigInt,bytesReceived: null == bytesReceived ? _self.bytesReceived : bytesReceived // ignore: cast_nullable_to_non_nullable
as BigInt,nacksSent: null == nacksSent ? _self.nacksSent : nacksSent // ignore: cast_nullable_to_non_nullable
as int,requestRetries: null == requestRetries ? _self.requestRetries : requestRetries // ignore: cast_nullable_to_non_nullable
as int,
  ));
}


}

// dart format on
