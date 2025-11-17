use akari_udp_core::{
    decode_packet,
    encode_error,
    encode_request,
    encode_response_chunk,
    encode_response_first_chunk,
    AkariError,
    Header,
    MessageType,
    Payload,
};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict};

fn map_error(err: AkariError) -> PyErr {
    PyValueError::new_err(err.to_string())
}

fn message_type_name(message_type: MessageType) -> &'static str {
    match message_type {
        MessageType::Req => "req",
        MessageType::Resp => "resp",
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

fn payload_to_dict<'py>(py: Python<'py>, payload: &Payload) -> PyResult<(&'static str, &'py PyDict)> {
    let dict = PyDict::new(py);
    match payload {
        Payload::Request(req) => {
            dict.set_item("url", req.url.as_str())?;
            Ok(("req", dict))
        }
        Payload::Response(chunk) => {
            dict.set_item("seq", chunk.seq)?;
            dict.set_item("seq_total", chunk.seq_total)?;
            dict.set_item("is_first", chunk.is_first)?;
            if let Some(code) = chunk.status_code {
                dict.set_item("status_code", code)?;
            }
            if let Some(len) = chunk.body_len {
                dict.set_item("body_len", len)?;
            }
            let chunk_bytes = PyBytes::new(py, &chunk.chunk);
            dict.set_item("chunk", chunk_bytes)?;
            Ok(("resp", dict))
        }
        Payload::Error(err) => {
            dict.set_item("error_code", err.error_code)?;
            dict.set_item("http_status", err.http_status)?;
            dict.set_item("message", err.message.as_str())?;
            Ok(("error", dict))
        }
    }
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
    let datagram = encode_response_first_chunk(status_code, body_len, body_chunk, message_id, seq_total, timestamp, psk).map_err(map_error)?;
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
fn decode_packet_py<'py>(py: Python<'py>, datagram: &'py [u8], psk: &'py [u8]) -> PyResult<&'py PyDict> {
    let parsed = decode_packet(datagram, psk).map_err(map_error)?;
    let header = header_to_dict(py, &parsed.header)?;
    let (type_name, payload) = payload_to_dict(py, &parsed.payload)?;

    let result = PyDict::new(py);
    result.set_item("header", header)?;
    result.set_item("type", type_name)?;
    result.set_item("payload", payload)?;
    Ok(result)
}

#[pymodule]
fn akari_udp_py(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(encode_request_py, m)?)?;
    m.add_function(wrap_pyfunction!(encode_response_first_chunk_py, m)?)?;
    m.add_function(wrap_pyfunction!(encode_response_chunk_py, m)?)?;
    m.add_function(wrap_pyfunction!(encode_error_py, m)?)?;
    m.add_function(wrap_pyfunction!(decode_packet_py, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use pyo3::types::PyDict;

    const PSK: &[u8] = b"integration-psk-123456";

    #[test]
    fn python_encode_decode_round_trip() {
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
}
