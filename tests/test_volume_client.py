import os
import sys
import shutil
import tempfile
import multiprocessing

import numpy
import vigra
import h5py

from dvidclient.volume_client import VolumeClient
from mockserver.h5mockserver import H5MockServer, H5CutoutRequestHandler

class TestVolumeClient(object):
    
    @classmethod
    def setupClass(cls):
        """
        Override.  Called by nosetests.
        """
        cls._tmp_dir = tempfile.mkdtemp()
        cls.test_filepath = os.path.join( cls._tmp_dir, "test_data.h5" )
        cls._generate_testdata_h5(cls.test_filepath)
        cls.server_proc = cls._start_mockserver( cls.test_filepath )

    @classmethod
    def teardownClass(cls):
        """
        Override.  Called by nosetests.
        """
        shutil.rmtree(cls._tmp_dir)
        cls.server_proc.terminate()

    @classmethod
    def _generate_testdata_h5(cls, test_filepath):
        """
        Generate a temporary hdf5 file for the mock server to use (and us to compare against)
        """
        # Generate some test data
        data = numpy.indices( (10, 100, 200, 3) )
        assert data.shape == (4, 10, 100, 200, 3)
        data = data.astype( numpy.uint32 )

        # Choose names
        cls.data_uuid = "abcde"
        cls.data_name = "indices_data"
        dataset_name = cls.data_uuid + '/' + cls.data_name

        # Write to h5 file
        with h5py.File( test_filepath, "w" ) as test_h5file:        
            dset = test_h5file.create_dataset(dataset_name, data=data)
            dset.attrs["axistags"] = vigra.defaultAxistags("tzyxc").toJSON()

    @classmethod
    def _start_mockserver(cls, h5filepath):
        """
        Start the mock DVID server in a separate process.
        """
        def server_main():
            server_address = ('', 8000)
            server = H5MockServer( h5filepath, server_address, H5CutoutRequestHandler )
            server.serve_forever()
    
        server_proc = multiprocessing.Process( target=server_main )
        server_proc.start()    
        return server_proc
    
    def test_cutout(self):
        """
        Get some data from the server and check it.
        """
        self._test_retrieve_volume( "localhost:8000", self.test_filepath, self.data_uuid, self.data_name, (0,50,5,9,0), (3,150,20,10,4) )
    
    def _test_retrieve_volume(self, hostname, h5filename, h5group, h5dataset, start, stop):
        """
        hostname: The dvid server host
        h5filename: The h5 file to compare against
        h5group: The hdf5 group, also used as the uuid of the dvid dataset
        h5dataset: The dataset name, also used as the name of the dvid dataset
        start, stop: The bounds of the cutout volume to retrieve from the server. FORTRAN ORDER.
        """
        # Retrieve from server
        dvid_vol = VolumeClient( hostname, uuid=h5group, dataset_name=h5dataset )
        try:
            subvolume = dvid_vol.retrieve_subvolume( start, stop )
        except VolumeClient.ErrorResponseException as ex:
            sys.stderr.write( 'DVID server returned an error in response to {}: {}, "{}"\n'.format( ex.attempted_action, ex.status_code, ex.reason ) )
            #if ex.status_code == 500: # Server internal error
            #    sys.stderr.write( 'Response body was:\n' )
            #    sys.stderr.write( ex.response_body )
            #    sys.stderr.write('\n')
            sys.stderr.flush()
            raise
        
        # Compare to file
        self._check_subvolume(h5filename, h5group, h5dataset, start, stop, subvolume)

    def test_push(self):
        # Cutout dims
        start, stop = (0,50,5,9,0), (3,150,20,10,4)
        shape = numpy.subtract( stop, start )

        # Generate test data
        subvolume = numpy.random.randint( 0,1000, shape ).astype( numpy.uint32 )
        subvolume = vigra.taggedView( subvolume, vigra.defaultAxistags('cxyzt') )

        # Run test.
        self._test_send_subvolume( "localhost:8000", self.test_filepath, self.data_uuid, self.data_name, start, stop, subvolume )

    def _test_send_subvolume(self, hostname, h5filename, h5group, h5dataset, start, stop, subvolume):
        # Send to server
        dvid_vol = VolumeClient( hostname, uuid=h5group, dataset_name=h5dataset )
        dvid_vol.modify_subvolume(start, stop, subvolume)
        
        # Check file
        self._check_subvolume(h5filename, h5group, h5dataset, start, stop, subvolume)        

    def _check_subvolume(self, h5filename, h5group, h5dataset, start, stop, subvolume):
        # Retrieve from file
        slicing = [ slice(x,y) for x,y in zip(start, stop) ]
        slicing = tuple(reversed(slicing))
        with h5py.File(h5filename, 'r') as f:
            expected_data = f[h5group][h5dataset][slicing]

        # Compare.
        assert ( subvolume.view(numpy.ndarray) == expected_data.transpose() ).all(),\
            "Data from server didn't match data from file!"

if __name__ == "__main__":
    import sys
    import nose
    sys.argv.append("--nocapture")    # Don't steal stdout.  Show it on the console as usual.
    sys.argv.append("--nologcapture") # Don't set the logging level to DEBUG.  Leave it alone.
    nose.run(defaultTest=__file__)
