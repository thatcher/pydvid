import numpy

from voxels_metadata import VoxelsMetadata

class VoxelsNddataCodec(object):

    # Data is sent to/retrieved from the http response stream in chunks.
    STREAM_CHUNK_SIZE = 1000 # (bytes)

    # Defined here for clients to use.
    VOLUME_MIMETYPE = "application/octet-stream"
    
    def __init__(self, voxels_metadata):
        """
        voxels_metadata: a VoxelsMetadata instance describing the remote volume.
        """
        assert isinstance(voxels_metadata, VoxelsMetadata)
        self._voxels_metadata = voxels_metadata
        
    def decode_to_ndarray(self, stream, full_roi_shape):
        """
        Decode the info in the given stream to a numpy.ndarray.
        
        Note: self._voxels_metadata.shape is IGNORED, because it refers to the entire DVID volume.
              Instead, the full_roi_shape parameter determines the size of the decoded dataset,
              including the channel dimension.
        """
        # Note that dvid uses fortran order indexing
        array = numpy.ndarray( full_roi_shape,
                               dtype=self._voxels_metadata.dtype,
                               order='F' )

        buf = numpy.getbuffer(array)
        self._read_to_buffer(buf, stream)

        return array

    def encode_from_ndarray(self, stream, array):
        """
        Encode the array to the given bytestream.
        
        Prerequisites:
        - array must be a numpy.ndarray
        - array must have the same dtype as this codec's metadata
        """
        buf = self._get_buffer(array)
        self._send_from_buffer(buf, stream)

    def create_encoded_stream_from_ndarray(self, array):
        """
        Create a stream object for the given array data.
        See VoxelsNddataCodec.EncodedStream for supported stream methods.

        Prerequisites:
        - array must be a numpy.ndarray
        - array must have the same dtype as this codec's metadata
        """
        buf = self._get_buffer(array)
        return VoxelsNddataCodec.EncodedStream(buf)

    def calculate_buffer_len(self, shape):
        return numpy.prod(shape) * self._voxels_metadata.dtype.type().nbytes
    
    def _get_buffer(self, array):
        """
        Obtain a buffer for the given array.

        Prerequisites:
        - array must be a numpy.ndarray
        - array must have the same dtype as this codec's metadata
        """
        # Check for bad input.
        assert isinstance( array, numpy.ndarray ), \
            "Expected a numpy.ndarray, not {}".format( type(array) )
        assert array.dtype == self._voxels_metadata.dtype, \
            "Wrong dtype.  Expected {}, got {}".format( self._voxels_metadata.dtype, array.dtype )

        # Unfortunately, if the array isn't F_CONTIGUOUS, we have to copy it.
        if not array.flags['F_CONTIGUOUS']:
            array_copy = numpy.empty_like(array, order='F')
            array_copy[:] = array[:]
            array = array_copy

        return numpy.getbuffer(array)
    
    @classmethod
    def _read_to_buffer(cls, buf, stream):
        """
        Read the data from the stream into the given buffer.
        """
        # We could read it in one step, but instead we'll read it in chunks to avoid big temporaries.
        # (See below.)
        # buf[:] = stream.read( len(buf) )

        # Read data from the stream in chunks
        remaining_bytes = len(buf)
        while remaining_bytes > 0:
            next_chunk_bytes = min( remaining_bytes, VoxelsNddataCodec.STREAM_CHUNK_SIZE )
            chunk_start = len(buf)-remaining_bytes
            chunk_stop = len(buf)-(remaining_bytes-next_chunk_bytes)
            buf[chunk_start:chunk_stop] = stream.read( next_chunk_bytes )
            remaining_bytes -= next_chunk_bytes

    @classmethod
    def _send_from_buffer(cls, buf, stream):
        """
        Write the given buffer out to the provided stream in chunks.
        """
        remaining_bytes = len(buf)
        while remaining_bytes > 0:
            next_chunk_bytes = min( remaining_bytes, VoxelsNddataCodec.STREAM_CHUNK_SIZE )
            chunk_start = len(buf)-remaining_bytes
            chunk_stop = len(buf)-(remaining_bytes-next_chunk_bytes)
            stream.write( buf[chunk_start:chunk_stop] )
            remaining_bytes -= next_chunk_bytes
        
    class EncodedStream(object):
        """
        A simple stream object returned by VoxelsNddataCodec.create_encoded_stream_from_ndarray()
        """
        def __init__(self, buf):
            assert buf is not None
            self._buffer = buf
            self._position = 0
        
        def seek(self, pos):
            self._position = pos
        
        def tell(self):
            return self._position
        
        def close(self):
            self._buffer = None
        
        def closed(self):
            return self._buffer is None
        
        @property
        def buf(self):
            return self._buffer

        def isatty(self):
            return False
        
        def getvalue(self):
            pos = self._position
            data = self.read()
            self._position = pos
            return data
        
        def peek(self, nbytes):
            return self._read(nbytes, True)
        
        def read(self, nbytes=None):
            return self._read(nbytes)

        def _read(self, nbytes=None, peeking=False):
            assert self._buffer is not None, "Can't read: stream is already closed."
            remaining_bytes = len(self._buffer) - self._position
            if nbytes is not None:
                nbytes = min(remaining_bytes, nbytes)

            start = self._position
            stop = self._position + nbytes
            encoded_data = self._buffer[start:stop]
            
            if not peeking:
                self._position  += nbytes
            return encoded_data
    