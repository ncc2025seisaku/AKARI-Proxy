use akari_udp_core::{
    decode_packet as decode_packet_core, decode_packet_v3, debug_dump, encode_ack_v2, encode_error, encode_error_v2,
    encode_nack_v2, encode_request, encode_request_v2, encode_resp_body_v3, encode_resp_head_cont_v3,
    encode_resp_head_v3, encode_response_chunk, encode_response_chunk_v2, encode_response_first_chunk,
    encode_response_first_chunk_v2, encode_error_v3, encode_nack_body_v3, encode_nack_head_v3, encode_request_v3,
    AkariError, Header, HeaderV3, MessageType, PacketTypeV3, Payload, PayloadV3, RequestMethod, ResponseChunk,
};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyString};

fn map_error(err: AkariError) -> PyErr {
    PyValueError::new_err(err.to_string())
}

fn message_type_name(message_type: MessageType) -> &'static str {
    match message_type {
        MessageType::Req => "req",
        MessageType::Resp => "resp",
        MessageType::Ack => "ack",
        MessageType::Nack => "nack",
        MessageType::Error => "error",
    }
}

fn header_to_dict<'py>(py: Python<'py>, header: &Header) -> PyResult<&'py PyDict> {
    let dict = PyDict::new(py);
    dict.set_item("version", header.version)?;
    dict.set_item("type", message_type_name(header.message_type))?;
    dict.set_item("flags", header.flags)?;
    dict.set_item("reserved", header.reserved)?;
    dict.set_item("message_id", header.message_id)?;
    dict.set_item("seq", header.seq)?;
    dict.set_item("seq_total", header.seq_total)?;
    dict.set_item("payload_len", header.payload_len)?;
    dict.set_item("timestamp", header.timestamp)?;
    Ok(dict)
}

fn header_v3_to_dict<'py>(py: Python<'py>, header: &HeaderV3) -> PyResult<&'py PyDict> {
    let dict = PyDict::new(py);
    dict.set_item("version", 3u8)?;
    dict.set_item(
        "type",
        match header.packet_type {
            PacketTypeV3::Req => "req",
            PacketTypeV3::RespHead => "resp-head",
            PacketTypeV3::RespHeadCont => "resp-head-cont",
            PacketTypeV3::RespBody => "resp-body",
            PacketTypeV3::NackHead => "nack-head",
            PacketTypeV3::NackBody => "nack-body",
            PacketTypeV3::Error => "error",
        },
    )?;
    dict.set_item("flags", header.flags)?;
    dict.set_item("message_id", header.message_id)?;
    dict.set_item("seq", header.seq)?;
    dict.set_item("seq_total", header.seq_total)?;
    dict.set_item("payload_len", header.payload_len)?;
    Ok(dict)
}

fn response_to_dict<'py>(py: Python<'py>, chunk: &ResponseChunk) -> PyResult<&'py PyDict> {
    let dict = PyDict::new(py);
    dict.set_item("seq", chunk.seq)?;
    dict.set_item("seq_total", chunk.seq_total)?;
    dict.set_item("is_first", chunk.is_first)?;
    if let Some(code) = chunk.status_code {
        dict.set_item("status_code", code)?;
    }
    if let Some(len) = chunk.body_len {
        dict.set_item("body_len", len)?;
    }
    if let Some(headers) = &chunk.headers {
        dict.set_item("headers", PyBytes::new(py, headers))?;
    }
    let chunk_bytes = PyBytes::new(py, &chunk.chunk);
    dict.set_item("chunk", chunk_bytes)?;
    Ok(dict)
}

fn payload_to_dict<'py>(py: Python<'py>, payload: &Payload) -> PyResult<(&'static str, &'py PyDict)> {
    let dict = PyDict::new(py);
    match payload {
        Payload::Request(req) => {
            dict.set_item("method", format!("{:?}", req.method).to_lowercase())?;
            dict.set_item("url", req.url.as_str())?;
            dict.set_item("headers", PyBytes::new(py, &req.headers))?;
            Ok(("req", dict))
        }
        Payload::Response(chunk) => {
            let resp_dict = response_to_dict(py, chunk)?;
            Ok(("resp", resp_dict))
        }
        Payload::Ack(ack) => {
            dict.set_item("first_lost_seq", ack.first_lost_seq)?;
            Ok(("ack", dict))
        }
        Payload::Nack(nack) => {
            dict.set_item("bitmap", PyBytes::new(py, &nack.bitmap))?;
            Ok(("nack", dict))
        }
        Payload::Error(err) => {
            dict.set_item("error_code", err.error_code)?;
            dict.set_item("http_status", err.http_status)?;
            dict.set_item("message", err.message.as_str())?;
            Ok(("error", dict))
        }
    }
}

fn payload_v3_to_dict<'py>(py: Python<'py>, payload: &PayloadV3) -> PyResult<(&'static str, &'py PyDict)> {
    let dict = PyDict::new(py);
    match payload {
        PayloadV3::Request(req) => {
            dict.set_item("method", format!("{:?}", req.method).to_lowercase())?;
            dict.set_item("url", req.url.as_str())?;
            dict.set_item("headers", PyBytes::new(py, &req.headers))?;
            Ok(("req", dict))
        }
        PayloadV3::RespHead(h) => {
            dict.set_item("status_code", h.status_code)?;
            dict.set_item("body_len", h.body_len)?;
            dict.set_item("hdr_chunks", h.hdr_chunks)?;
            dict.set_item("hdr_idx", h.hdr_idx)?;
            dict.set_item("seq_total_body", h.seq_total_body)?;
            dict.set_item("headers", PyBytes::new(py, &h.header_block))?;
            Ok(("resp-head", dict))
        }
        PayloadV3::RespHeadCont { hdr_idx, hdr_chunks, header_block } => {
            dict.set_item("hdr_idx", hdr_idx)?;
            dict.set_item("hdr_chunks", hdr_chunks)?;
            dict.set_item("headers", PyBytes::new(py, header_block))?;
            Ok(("resp-head-cont", dict))
        }
        PayloadV3::RespBody(b) => {
            dict.set_item("seq", b.seq)?;
            dict.set_item("seq_total", b.seq_total)?;
            dict.set_item("chunk", PyBytes::new(py, &b.chunk))?;
            Ok(("resp-body", dict))
        }
        PayloadV3::NackHead(n) => {
            dict.set_item("bitmap", PyBytes::new(py, &n.bitmap))?;
            Ok(("nack-head", dict))
        }
        PayloadV3::NackBody(n) => {
            dict.set_item("bitmap", PyBytes::new(py, &n.bitmap))?;
            Ok(("nack-body", dict))
        }
        PayloadV3::Error(err) => {
            dict.set_item("error_code", err.error_code)?;
            dict.set_item("http_status", err.http_status)?;
            dict.set_item("message", err.message.as_str())?;
            Ok(("error", dict))
        }
    }
}

fn parse_method_from_py(method: &PyAny) -> PyResult<RequestMethod> {
    if let Ok(as_str) = method.downcast::<PyString>() {
        let lower = as_str.to_str()?.to_ascii_lowercase();
        return match lower.as_str() {
            "get" => Ok(RequestMethod::Get),
            "head" => Ok(RequestMethod::Head),
            "post" => Ok(RequestMethod::Post),
            _ => Err(PyValueError::new_err("method must be get/head/post")),
        };
    }
    if let Ok(code) = method.extract::<u8>() {
        return match code {
            0 => Ok(RequestMethod::Get),
            1 => Ok(RequestMethod::Head),
            2 => Ok(RequestMethod::Post),
            _ => Err(PyValueError::new_err("method code must be 0,1,2")),
        };
    }
    Err(PyValueError::new_err("method must be str or int"))
}

#[pyfunction]
fn encode_request_py(
    py: Python,
    url: &str,
    message_id: u64,
    timestamp: u32,
    psk: &[u8],
) -> PyResult<Py<PyBytes>> {
    let datagram = encode_request(url, message_id, timestamp, psk).map_err(map_error)?;
    Ok(PyBytes::new(py, &datagram).into())
}

#[pyfunction]
fn encode_request_v2_py(
    py: Python,
    method: &PyAny,
    url: &str,
    header_block: &[u8],
    message_id: u64,
    timestamp: u32,
    flags: u8,
    psk: &[u8],
) -> PyResult<Py<PyBytes>> {
    let method = parse_method_from_py(method)?;
    let datagram = encode_request_v2(method, url, header_block, message_id, timestamp, flags, psk).map_err(map_error)?;
    Ok(PyBytes::new(py, &datagram).into())
}

#[pyfunction]
fn encode_response_first_chunk_py(
    py: Python,
    status_code: u16,
    body_len: u32,
    body_chunk: &[u8],
    message_id: u64,
    seq_total: u16,
    timestamp: u32,
    psk: &[u8],
) -> PyResult<Py<PyBytes>> {
    let datagram =
        encode_response_first_chunk(status_code, body_len, body_chunk, message_id, seq_total, timestamp, psk)
            .map_err(map_error)?;
    Ok(PyBytes::new(py, &datagram).into())
}

#[pyfunction]
fn encode_response_first_chunk_v2_py(
    py: Python,
    status_code: u16,
    body_len: u32,
    header_block: &[u8],
    body_chunk: &[u8],
    message_id: u64,
    seq_total: u16,
    flags: u8,
    timestamp: u32,
    psk: &[u8],
) -> PyResult<Py<PyBytes>> {
    let datagram = encode_response_first_chunk_v2(
        status_code,
        body_len,
        header_block,
        body_chunk,
        message_id,
        seq_total,
        flags,
        timestamp,
        psk,
    )
    .map_err(map_error)?;
    Ok(PyBytes::new(py, &datagram).into())
}

#[pyfunction]
fn encode_response_chunk_py(
    py: Python,
    body_chunk: &[u8],
    message_id: u64,
    seq: u16,
    seq_total: u16,
    timestamp: u32,
    psk: &[u8],
) -> PyResult<Py<PyBytes>> {
    let datagram = encode_response_chunk(body_chunk, message_id, seq, seq_total, timestamp, psk).map_err(map_error)?;
    Ok(PyBytes::new(py, &datagram).into())
}

#[pyfunction]
fn encode_response_chunk_v2_py(
    py: Python,
    body_chunk: &[u8],
    message_id: u64,
    seq: u16,
    seq_total: u16,
    flags: u8,
    timestamp: u32,
    psk: &[u8],
) -> PyResult<Py<PyBytes>> {
    let datagram =
        encode_response_chunk_v2(body_chunk, message_id, seq, seq_total, flags, timestamp, psk).map_err(map_error)?;
    Ok(PyBytes::new(py, &datagram).into())
}

#[pyfunction]
fn encode_error_py(
    py: Python,
    error_code: u8,
    http_status: u16,
    message: &str,
    message_id: u64,
    timestamp: u32,
    psk: &[u8],
) -> PyResult<Py<PyBytes>> {
    let datagram = encode_error(error_code, http_status, message, message_id, timestamp, psk).map_err(map_error)?;
    Ok(PyBytes::new(py, &datagram).into())
}

#[pyfunction]
fn encode_error_v2_py(
    py: Python,
    error_code: u8,
    http_status: u16,
    message: &str,
    message_id: u64,
    timestamp: u32,
    psk: &[u8],
) -> PyResult<Py<PyBytes>> {
    let datagram = encode_error_v2(error_code, http_status, message, message_id, timestamp, psk).map_err(map_error)?;
    Ok(PyBytes::new(py, &datagram).into())
}

#[pyfunction]
fn encode_ack_v2_py(py: Python, first_lost_seq: u16, message_id: u64, timestamp: u32, psk: &[u8]) -> PyResult<Py<PyBytes>> {
    let datagram = encode_ack_v2(first_lost_seq, message_id, timestamp, psk).map_err(map_error)?;
    Ok(PyBytes::new(py, &datagram).into())
}

#[pyfunction]
fn encode_nack_v2_py(py: Python, bitmap: &[u8], message_id: u64, timestamp: u32, psk: &[u8]) -> PyResult<Py<PyBytes>> {
    let datagram = encode_nack_v2(bitmap, message_id, timestamp, psk).map_err(map_error)?;
    Ok(PyBytes::new(py, &datagram).into())
}

// ---------- v3 encode ----------
#[pyfunction]
fn encode_request_v3_py(
    py: Python,
    method: &PyAny,
    url: &str,
    header_block: &[u8],
    message_id: u64,
    flags: u8,
    timestamp: u32,
    psk: &[u8],
) -> PyResult<Py<PyBytes>> {
    let method = parse_method_from_py(method)?;
    let datagram = encode_request_v3(method, url, header_block, message_id, timestamp, flags, psk).map_err(map_error)?;
    Ok(PyBytes::new(py, &datagram).into())
}

#[pyfunction]
fn encode_resp_head_v3_py(
    py: Python,
    status_code: u16,
    header_block: &[u8],
    body_len: u32,
    hdr_chunks: u8,
    hdr_idx: u8,
    seq_total_body: u16,
    flags: u8,
    message_id: u64,
    psk: &[u8],
) -> PyResult<Py<PyBytes>> {
    let datagram = encode_resp_head_v3(
        status_code,
        header_block.len(),
        header_block,
        body_len,
        hdr_chunks,
        hdr_idx,
        seq_total_body,
        flags,
        message_id,
        psk,
    )
    .map_err(map_error)?;
    Ok(PyBytes::new(py, &datagram).into())
}

#[pyfunction]
fn encode_resp_head_cont_v3_py(
    py: Python,
    header_block: &[u8],
    hdr_idx: u8,
    hdr_chunks: u8,
    flags: u8,
    message_id: u64,
    psk: &[u8],
) -> PyResult<Py<PyBytes>> {
    let datagram = encode_resp_head_cont_v3(header_block, hdr_idx, hdr_chunks, flags, message_id, psk).map_err(map_error)?;
    Ok(PyBytes::new(py, &datagram).into())
}

#[pyfunction]
fn encode_resp_body_v3_py(
    py: Python,
    body_chunk: &[u8],
    seq: u16,
    seq_total: u16,
    flags: u8,
    message_id: u64,
    psk: &[u8],
) -> PyResult<Py<PyBytes>> {
    let datagram = encode_resp_body_v3(body_chunk, seq, seq_total, flags, message_id, psk).map_err(map_error)?;
    Ok(PyBytes::new(py, &datagram).into())
}

#[pyfunction]
fn encode_nack_head_v3_py(py: Python, bitmap: &[u8], message_id: u64, flags: u8, psk: &[u8]) -> PyResult<Py<PyBytes>> {
    let datagram = encode_nack_head_v3(bitmap, message_id, flags, psk).map_err(map_error)?;
    Ok(PyBytes::new(py, &datagram).into())
}

#[pyfunction]
fn encode_nack_body_v3_py(py: Python, bitmap: &[u8], message_id: u64, flags: u8, psk: &[u8]) -> PyResult<Py<PyBytes>> {
    let datagram = encode_nack_body_v3(bitmap, message_id, flags, psk).map_err(map_error)?;
    Ok(PyBytes::new(py, &datagram).into())
}

#[pyfunction]
fn encode_error_v3_py(py: Python, message: &str, code: u8, http_status: u16, message_id: u64, flags: u8, psk: &[u8]) -> PyResult<Py<PyBytes>> {
    let datagram = encode_error_v3(message, code, http_status, message_id, flags, psk).map_err(map_error)?;
    Ok(PyBytes::new(py, &datagram).into())
}
#[pyfunction]
fn decode_packet_py<'py>(py: Python<'py>, datagram: &'py [u8], psk: &'py [u8]) -> PyResult<&'py PyDict> {
    let parsed = decode_packet_core(datagram, psk).map_err(map_error)?;
    let header = header_to_dict(py, &parsed.header)?;
    let (type_name, payload) = payload_to_dict(py, &parsed.payload)?;

    let result = PyDict::new(py);
    result.set_item("header", header)?;
    result.set_item("type", type_name)?;
    result.set_item("payload", payload)?;
    Ok(result)
}

#[pyfunction]
fn decode_packet_v3_py<'py>(py: Python<'py>, datagram: &'py [u8], psk: &'py [u8]) -> PyResult<&'py PyDict> {
    let parsed = decode_packet_v3(datagram, psk).map_err(map_error)?;
    let header = header_v3_to_dict(py, &parsed.header)?;
    let (type_name, payload) = payload_v3_to_dict(py, &parsed.payload)?;
    let result = PyDict::new(py);
    result.set_item("header", header)?;
    result.set_item("type", type_name)?;
    result.set_item("payload", payload)?;
    Ok(result)
}

/// Auto decode: try v3, fallback to v1/v2
#[pyfunction]
fn decode_packet_auto_py<'py>(py: Python<'py>, datagram: &'py [u8], psk: &'py [u8]) -> PyResult<&'py PyDict> {
    match decode_packet_v3(datagram, psk) {
        Ok(parsed) => {
            let header = header_v3_to_dict(py, &parsed.header)?;
            let (type_name, payload) = payload_v3_to_dict(py, &parsed.payload)?;
            let result = PyDict::new(py);
            result.set_item("header", header)?;
            result.set_item("type", type_name)?;
            result.set_item("payload", payload)?;
            Ok(result)
        }
        Err(_) => decode_packet_py(py, datagram, psk),
    }
}

#[pyfunction]
fn debug_dump_py(datagram: &[u8], psk: &[u8]) -> PyResult<String> {
    debug_dump(datagram, psk).map_err(map_error)
}

#[pymodule]
fn akari_udp_py(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(encode_request_py, m)?)?;
    m.add_function(wrap_pyfunction!(encode_request_v2_py, m)?)?;
    m.add_function(wrap_pyfunction!(encode_response_first_chunk_py, m)?)?;
    m.add_function(wrap_pyfunction!(encode_response_first_chunk_v2_py, m)?)?;
    m.add_function(wrap_pyfunction!(encode_response_chunk_py, m)?)?;
    m.add_function(wrap_pyfunction!(encode_response_chunk_v2_py, m)?)?;
    m.add_function(wrap_pyfunction!(encode_error_py, m)?)?;
    m.add_function(wrap_pyfunction!(encode_error_v2_py, m)?)?;
    m.add_function(wrap_pyfunction!(encode_ack_v2_py, m)?)?;
    m.add_function(wrap_pyfunction!(encode_nack_v2_py, m)?)?;
    // v3
    m.add_function(wrap_pyfunction!(encode_request_v3_py, m)?)?;
    m.add_function(wrap_pyfunction!(encode_resp_head_v3_py, m)?)?;
    m.add_function(wrap_pyfunction!(encode_resp_head_cont_v3_py, m)?)?;
    m.add_function(wrap_pyfunction!(encode_resp_body_v3_py, m)?)?;
    m.add_function(wrap_pyfunction!(encode_nack_head_v3_py, m)?)?;
    m.add_function(wrap_pyfunction!(encode_nack_body_v3_py, m)?)?;
    m.add_function(wrap_pyfunction!(encode_error_v3_py, m)?)?;
    m.add_function(wrap_pyfunction!(decode_packet_py, m)?)?;
    m.add_function(wrap_pyfunction!(decode_packet_v3_py, m)?)?;
    m.add_function(wrap_pyfunction!(decode_packet_auto_py, m)?)?;
    m.add_function(wrap_pyfunction!(debug_dump_py, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use pyo3::types::PyDict;

    const PSK: &[u8] = b"integration-psk-123456";

    #[test]
    fn python_encode_decode_round_trip_v1() {
        Python::with_gil(|py| {
            let datagram = encode_request_py(py, "https://example.xyz", 0x1234_5678, 0x5f3759df, PSK).expect("encode");
            let dict = decode_packet_py(py, datagram.as_bytes(py), PSK).expect("decode");
            let payload_any = dict
                .get_item("payload")
                .expect("payload lookup")
                .expect("payload missing");
            let payload: &PyDict = payload_any.downcast::<PyDict>().unwrap();
            let url_value = payload
                .get_item("url")
                .expect("url lookup")
                .expect("url missing");
            let url = url_value.extract::<&str>().unwrap();
            assert_eq!(url, "https://example.xyz");
        });
    }

    #[test]
    fn python_encode_decode_round_trip_v2() {
        Python::with_gil(|py| {
            let hdr = b"\x01\x03abc";
            let datagram = encode_request_v2_py(
                py,
                PyString::new(py, "get"),
                "https://example.xyz",
                hdr,
                0x1234_5678,
                0x5f3759df,
                0x40,
                PSK,
            )
                .expect("encode");
            let dict = decode_packet_py(py, datagram.as_bytes(py), PSK).expect("decode");
            let payload_any = dict.get_item("payload").unwrap().unwrap();
            let payload: &PyDict = payload_any.downcast::<PyDict>().unwrap();
            let url_value = payload.get_item("url").unwrap().unwrap();
            let url = url_value.extract::<&str>().unwrap();
            assert_eq!(url, "https://example.xyz");
            let headers: &PyBytes = payload.get_item("headers").unwrap().unwrap().downcast::<PyBytes>().unwrap();
            assert_eq!(headers.as_bytes(), hdr);
        });
    }

    #[test]
    fn python_decode_hmac_failure_propagates() {
        Python::with_gil(|py| {
            let datagram = encode_request_py(py, "https://example.xyz", 0xaa55, 0xff, PSK).unwrap();
            let buffer = datagram.as_bytes(py).to_vec();
            let mut mutated = buffer.clone();
            let last = mutated.len() - 1;
            mutated[last] ^= 0x01;
            let err = decode_packet_py(py, &mutated, PSK);
            assert!(err.is_err());
        });
    }

    #[test]
    fn python_debug_dump_returns_text() {
        Python::with_gil(|py| {
            let datagram = encode_request_py(py, "https://example.xyz", 0x11, 0x22, PSK).unwrap();
            let dump = debug_dump_py(datagram.as_bytes(py), PSK).unwrap();
            assert!(dump.contains("AKARI-UDP Packet Debug"));
            assert!(dump.contains("Request"));
        });
    }
}
