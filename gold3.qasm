OPENQASM 3.0;
include "stdgates.inc";
qubit[3] q;
cry(3*pi/4) q[0], q[1];
cry(3*pi/4) q[2], q[1];
